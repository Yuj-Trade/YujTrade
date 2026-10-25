# Proposal: add-continuous-model-learning

## Why

Models are already trained and stored per symbol and timeframe
(`artifacts/<symbol>/<timeframe>/<model_type>/`, `ModelManager.get_model` keys
by `f"{model_type}-{symbol}-{timeframe}"`), but nothing refreshes them after the
initial `scripts/train_models.py` run.

`predict_with_confidence` refuses to train (`model_auto_train_on_predict=false`,
a frozen contract), so an artifact that was trained once keeps predicting on an
ever-older view of the market. In the 2026-10-24 run every symbol reported
`model_unavailable: ... is not trained`, which is the same gap from the other
side: no artifact, and no mechanism that produces one while the bot runs.

The user wants learning to happen during operation, per symbol, alongside the
cached data that makes retraining cheap.

## What Changes

- A `ModelLearner` service (`modeling/learner.py`) that retrains one
  symbol/timeframe/model-type at a time in the existing training executor,
  after the analysis cycle that used it, without blocking that cycle.
- Learning is incremental: it warm-starts from the currently promoted artifact
  and merges the freshly cached candles instead of training from scratch.
- Each candidate goes through the existing guards: feature-drift detection
  (`modeling/drift.py`), OOS metrics, and guarded promotion with rollback
  (`modeling/promotion.py`). A candidate that degrades directional accuracy is
  stored but not promoted.
- Scheduling is bounded and idempotent: one in-flight job per
  symbol/timeframe/model-type, a minimum interval between attempts, a minimum
  number of new candles, and a bounded worker pool.
- Configuration block `model_learning` in `ConfigManager.DEFAULT_CONFIG`
  (`enabled`, `min_interval_minutes`, `min_new_candles`, `max_concurrency`,
  `model_types`, `promote`).
- Failure of any learning job is contained: it logs once and never propagates
  into signal generation.

## Non-goals

- Training inside `predict_with_confidence`. The frozen contract
  `model_auto_train_on_predict=false` stays; learning is a separate, explicit
  service.
- Changing model architectures, hyper-parameters or `LONG_TERM_CONFIG`
  thresholds.
- Live execution.
- A feature store; the learner consumes the same `get_data_for_model` contract.

## Impact

- Affected specs: `model-learning` (new)
- Affected code: `modeling/learner.py` (new), `services/trading_service.py`,
  `config/settings.py`, `main.py` (shutdown ordering)
- Tests: new `tests/unit/modeling/test_learner.py`; existing model lifecycle
  tests stay green
- Behaviour: new artifact versions appear during operation. Promotion remains
  guarded, so signals change only when a candidate passes the same gates a
  manual training run must pass.
