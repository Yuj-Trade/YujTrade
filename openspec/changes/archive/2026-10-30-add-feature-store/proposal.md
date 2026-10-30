# Proposal: add-feature-store

Approval: approved by YT-IMPL-SPEC Revision 2.0 (2026-10-29), decision G1.

## Why

No feature store exists. The only capture is one JSON file per signal
(`runs/feature_vectors/<signal_id>.json`), which holds the indicator results
and the ML predictions but not the exact model input vector. Training can
therefore never reuse the rows a live model actually saw, and the
prediction window (300 candles) differs from the training window, so the
feature space is skewed between training and inference.

## What Changes

- `features/feature_store.py` stores one row per
  `(symbol, timeframe, candle_time, feature_set_hash)` with the ordered
  feature list and the canonical JSON values, and one label row per vector.
- `ModelManager.predict_with_confidence` returns the model input vector
  alongside its result, and the signal generator records it when the store
  is enabled.
- The learner labels pending vectors from the frame it already fetched and
  can train from the store when configured.
- Both tables are append-only by trigger.
- **BREAKING** for `predict_with_confidence`: the result carries the vector.

## Impact

- Affected specs: `feature-store`, `model-learning`
- Affected code: `features/feature_store.py` (new),
  `modeling/model_manager.py`, `strategy/signal_generator.py`,
  `modeling/models.py`, `modeling/learner.py`, `services/trading_service.py`,
  `config/settings.py`
- Disabled by default (`feature_store_enabled = false`); the committed
  signal behaviour is unchanged.
