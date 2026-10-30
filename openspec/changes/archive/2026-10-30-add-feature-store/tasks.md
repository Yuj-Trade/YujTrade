## 1. Schema and capture (P7)
- [x] 1.1 `features/feature_store.py` with both tables and their triggers
- [x] 1.2 `record_vector`, `label_pending`, `training_frame`
- [x] 1.3 `predict_with_confidence` returns the model input vector
- [x] 1.4 The signal generator records the vector when enabled
- [x] 1.5 Configuration keys, `create_trading_stack` wiring

## 2. Training source (P7)
- [x] 2.1 The XGBoost path accepts an optional feature frame
- [x] 2.2 `LearningSettings.training_source` and the fallback
- [x] 2.3 Tests: schema, triggers, leakage, parity, fallback, unchanged signal
