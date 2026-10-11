# ADR-0003: Artifact availability

Status: accepted.

## Context

Implicit training on the prediction path is a production hazard: a missing
model silently triggers network-heavy fitting, unbounded latency, and
non-reproducible predictions. Operators need a bright line between "model
missing" (expected, degradable) and "prediction broken" (unexpected).

## Decision

Prediction never trains. `ModelManager.predict_with_confidence` returns `None`
with an explicit `model_unavailable` log event when the artifact pointer
(`artifacts/<symbol>/<timeframe>/<model_type>/current.json`), the model
files, the input data, or the prediction itself is missing or invalid.
Training is an explicit model-management action only
(`train_models.py`, `train_model`, `train_and_save_model`). Versions are
recorded by `ArtifactRegistry.create_version` with an 11-field
`metadata.json`; calibration samples are namespaced per
`(model_type, symbol, timeframe)` so models cannot borrow each other's
calibration.

## Consequences

- The scorer degrades the ML component to zero instead of failing the
  analysis when a model is absent.
- `tests/unit/modeling/test_artifacts.py` pins the lifecycle: metadata
  round-trip, per-model calibration keys, no-train-on-predict, and the
  `close.shift(-1)` label with last-row purge.
- Cost: a fresh deployment predicts without ML until someone explicitly
  trains; this is intended and visible in logs.
