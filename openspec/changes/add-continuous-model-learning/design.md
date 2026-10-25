# Design: add-continuous-model-learning

## Context

`ModelManager.train_model` already does everything a safe retrain needs: warm
start, OOS metrics, artifact versioning and optional promotion. What is missing
is a caller that decides *when* to retrain and that does so without stalling the
analysis cycle.

Two constraints shape the design:

- `predict_with_confidence` must not train (`model_auto_train_on_predict=false`).
  Signal generation has a latency budget and a training run takes minutes.
- `LONG_TERM_CONFIG` thresholds and the model data contract are frozen. The
  learner may not invent limits; it reads them from `ConfigManager`
  (`model_data_limits`, `model_prediction_limit`).

## Goals / Non-Goals

- Goals: per-symbol continuous learning during operation; bounded resource use;
  no cycle latency impact; guarded promotion; full audit trail through the
  existing artifact registry.
- Non-Goals: online learning inside a single prediction, new model families,
  streaming updates, threshold changes.

## Decisions

- **Decision: a separate `ModelLearner`, not a flag inside predict.**
  Training is scheduled by the service that owns the cycle, so the frozen
  prediction contract is untouched and the learner can be enabled, disabled and
  tested on its own.
  *Alternative considered:* flipping `model_auto_train_on_predict` and training
  inline. Rejected: it blocks a cycle for minutes, breaks the golden
  determinism assumption, and makes prediction latency unbounded.

- **Decision: trigger after the cycle, not during it.**
  `TradingService.run_analysis_for_all_symbols` and `run_quick_analysis` already
  bracket a cycle with `begin_run_cycle`/`end_run_cycle`. The learner is asked
  for the symbols that cycle touched, after the cycle result is returned.
  *Alternative considered:* per-symbol trigger inside `analyze_symbol`.
  Rejected: it interleaves training with data fetching and multiplies lock
  contention.

- **Decision: warm start from the promoted artifact.**
  `train_model(warm_start=True)` continues from the current weights, so a
  retrain on a few hundred new candles costs a fraction of a cold fit.
  If no artifact exists the learner falls back to a cold fit, which is exactly
  what the first-run gap needs.

- **Decision: guarded promotion, unchanged.**
  The learner calls `train_model(promote=config.model_learning.promote)` and
  relies on `promotion.py` to reject a candidate whose directional accuracy
  drops beyond `promotion_max_directional_accuracy_drop`. A rejected candidate
  is still versioned, so nothing is lost.

- **Decision: one in-flight job per key plus a minimum interval.**
  A set of in-flight keys and a `last_attempt` map make the learner idempotent
  across overlapping cycles and prevent a hot symbol from retraining every
  minute.

- **Decision: consume the cached candles.**
  The learner calls the same `get_data_for_model` contract, which now reads the
  durable OHLCV store first (`add-ohlcv-cache-store`). Retraining therefore adds
  no upstream requests when the store is warm.

## Risks / Trade-offs

- **Training competes with prediction for CPU** → bounded worker pool
  (`max_concurrency`), the existing `ModelTrainingExecutor` sizing, and a
  minimum interval between jobs.
- **A bad candidate could degrade signals** → promotion gates stay in force and
  are the same ones a manual training run must pass; the learner never writes a
  `current.json` pointer directly.
- **Memory growth from many cached models** → the learner reuses
  `ModelManager.get_model`, whose cache already evicts closed models, and the
  existing `cleanup()` path is used for non-promoted candidates.
- **Long-running job at shutdown** → jobs run in the existing executor, which
  `shutdown()` cancels with `cancel_futures=True`.

## Migration Plan

1. Ship the learner disabled (`model_learning.enabled=false`).
2. Enable in `config.json` for one timeframe, verify artifact versions and
   promotion outcomes in `artifacts/`.
3. Enable for all timeframes.

Rollback: set `model_learning.enabled=false`; already-promoted versions can be
reverted with the existing registry pointer.

## Open Questions

- Should a rejected candidate be retried with a longer interval? Current
  proposal: yes, the interval doubles per consecutive rejection up to a cap.
- Should learning run when the model has never been trained but the market is
  closed? Timeframes are continuous for crypto, so no.
