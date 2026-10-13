# ADR-0007: Artifact integrity

Status: accepted.

## Context

Model versions recorded no usable metadata (empty feature lists, unknown
commits, no file hashes), and scalers persisted via pickle, so a tampered
artifact could execute arbitrary code on load.

## Decision

`create_version` requires full metadata (`data_start`, `data_end`,
`feature_list`, `params`, `git_commit`, `library_versions`, `files_sha256`)
built by `build_metadata`, and verifies stored hashes against the copied
files. Loads re-verify through `verify_current`; any mismatch raises
`ArtifactIntegrityError`, which the manager reports as `model_unavailable`
instead of crashing. Scalers persist as validated sorted-key JSON
(`modeling/scaler_io.py`) for the three supported scaler types; legacy
`scaler_*.pkl` files are never deserialized.

## Consequences

- Artifacts written before this change no longer load; every model must be
  retrained once (`python scripts/train_models.py`).
- Training records out-of-sample `rmse` and `directional_accuracy` from the
  last 20% of data with a one-row purge, for both model types.
- Unsupported scaler types raise `TypeError` at save time, failing loudly
  instead of persisting an unloadable blob.
