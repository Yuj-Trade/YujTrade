# Tasks: add-continuous-model-learning

## 1. Configuration

- [x] 1.1 Add `model_learning` to `ConfigManager.DEFAULT_CONFIG`: `enabled`,
  `min_interval_minutes`, `min_new_candles`, `max_concurrency`, `model_types`,
  `promote`, `max_consecutive_rejections`

## 2. Learner

- [x] 2.1 Add `modeling/learner.py` with `ModelLearner` holding `ModelManager`,
  a `data_provider`, a config snapshot and an injected clock
- [x] 2.2 Implement `request(symbols, timeframe)` that enqueues eligible keys
  and returns immediately
- [x] 2.3 Implement eligibility: enabled, in-flight guard, minimum interval with
  exponential backoff on rejection, minimum new candles from the store coverage
- [x] 2.4 Run jobs through a bounded `asyncio.Semaphore` and
  `train_model(warm_start=True, promote=...)`
- [x] 2.5 Record per-key outcome (promoted / rejected / failed) and log once

## 3. Wiring

- [x] 3.1 Call `learner.request(...)` after `run_analysis_for_all_symbols` and
  `run_quick_analysis` return
- [x] 3.2 Construct the learner in `create_trading_stack()` and shut it down in
  `TradingService.cleanup()`
- [x] 3.3 Keep `model_auto_train_on_predict` false and assert it in a test

## 4. Verification

- [x] 4.1 Unit tests: non-blocking scheduling, one job per key, interval gate,
  minimum-new-candles gate, warm start, rejected candidate not promoted,
  failure isolation
- [x] 4.2 Run the default gate plus `ruff check`, `ruff format --check`,
  `mypy domain`; confirm golden hashes unchanged
