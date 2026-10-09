# ADR-0003: Artifact availability

Prediction never trains a missing model when `model_auto_train_on_predict` is
false. Missing or untrained artifacts produce the explicit
`model_unavailable` event; training remains an explicit model-management action.
