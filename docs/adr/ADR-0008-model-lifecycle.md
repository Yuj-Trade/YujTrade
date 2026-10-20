# ADR-0008: Model lifecycle (drift, warm start, guarded promotion)

Status: accepted.

## Context

`scripts/train_models.py` retrained every symbol and timeframe and promoted
the result unconditionally. Nothing detected that the data the model was
trained on had changed, nothing detected that the new model was worse than
the old one, and nothing recorded which features a live decision actually
saw. A single bad retrain could therefore silently replace a good model, and
no past signal could be reconstructed after the fact.

## Decision

**Drift is a data statement, measured on stationary features.**
`modeling/drift.py` implements the two-sample Kolmogorov-Smirnov test in pure
Python (no new dependency) and compares a reference window against a live
window per feature. Price levels are never tested directly: a trending series
drifts trivially. The tested features are `close_return_1`, `close_return_5`,
`volume_return_1` and `intrabar_range`.

Three statistical properties are deliberate:

- **Dependency-aware sampling.** Multi-bar features overlap, so their samples
  are autocorrelated and the KS p-value's independence assumption would not
  hold. Each feature is therefore sampled with a stride equal to its
  dependency length (`close_return_5` uses stride 5), which restores
  independence at the cost of fewer effective samples.
- **Multiple-testing correction.** Four features tested at a nominal 5% would
  raise a false alarm in roughly 18% of runs. The detector applies a
  Bonferroni correction (`alpha / feature_count`) so the family-wise error
  rate stays at the configured `drift_alpha`.
- **Absence of evidence is not evidence.** A window smaller than
  `drift_min_window` effective samples yields `status="insufficient_data"`
  and `drifted=False`. The detector never invents a signal it cannot support.

The p-value uses the finite-sample corrected Kolmogorov argument
(`en + 0.12 + 0.11/en`) and is implemented with the complementary
(Theta) form for small arguments, where the alternating series converges too
slowly to truncate safely. It matches the reference implementation to machine
precision.

**Promotion is a separate, explicit step.**
`modeling/promotion.py` holds a pure decision function over
`(baseline_metrics, candidate_metrics, policy)`. Training always writes a new
version directory with `update_current=False`; promotion is a distinct pointer
write through `ArtifactRegistry.promote_version`. A candidate is rejected
when its directional accuracy drops by more than
`promotion_max_directional_accuracy_drop`, when its RMSE grows beyond
`promotion_max_rmse_increase_ratio`, or when its metrics are missing or NaN.
Unknown quality is not acceptable quality, so an unmeasurable candidate is
never promoted. A rejected candidate is retained on disk for forensics and
leaves the promoted pointer untouched.

**Training writes to a staging path, never into a promoted version.**
A model object resolves its file paths from its own `model_path`, and the
manager points that path at the promoted artifact directory so the model can
be loaded from it. Left alone, `fit()` would then save the new weights *into
the promoted version directory*, invalidating the recorded `files_sha256` and
making the promoted artifact fail its own integrity check. Training therefore
redirects the model to a staging directory before fitting; the artifact
registry copies the staged files into the new version directory. A candidate
that is not promoted is also evicted from the in-memory cache, so the next
prediction reloads the promoted artifact instead of silently using the
rejected weights. This is what makes the rollback guarantee real rather than
nominal.

**Warm start continues; it never refits the feature space.**
`--warm-start` reloads the current artifact (weights plus the persisted JSON
scaler) and continues from it. The scaler is deliberately *not* refitted during
a warm start: a continued model must see the same feature space it was
trained in, and refitting the scaler would silently invalidate the loaded
weights. `XGBoostModel` continues the persisted booster; `LSTMModel` restores
the persisted weights into the rebuilt network. Keras optimizer momentum is
not part of the artifact contract and is not restored.

**Prediction-time features are recorded, not inferred.**
`strategy/prediction_trace.py` writes the feature schema and values behind
each emitted signal to `runs/feature_vectors/<signal_id>.json`. The recorder
is an optional dependency of `SignalGenerator`; it is wired only when
`prediction_trace_enabled` is true, and a trace failure degrades to a warning
and never blocks the signal.

## Consequences

- `scripts/train_models.py` gains a real CLI: `--dry-run` (drift check only,
  exit code 2 on drift), `--warm-start`, `--data` (local CSV instead of the
  network), `--symbol`, `--timeframe`, `--only-on-drift`, `--report` and
  `--no-rollback-guard`.
- The live window is timeframe-aware (`drift_live_windows`), because the
  number of effective samples — not the number of bars — is what determines
  whether a feature can be tested at all.
- Network training stays user-side. CI runs the drift check and the
  walk-forward validation against committed fixtures only, and never promotes
  an artifact.
- A feature store usable for training reuse remains deferred behind an
  OpenSpec proposal; the prediction trace is the read-side prerequisite.
- `ModelManager.train_model` returns a `TrainingOutcome` (version, promotion
  state, fresh OOS metrics) instead of a bare boolean, so callers decide
  promotion on evidence rather than on a truthy value.
