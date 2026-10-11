# ADR-0005: Holdout isolation

Status: accepted.

## Context

Walk-forward validation still reuses every row for some fold's training
set. A final untouched slice is needed to detect overfitting to the
validation procedure itself — but any routine, repeatable access pattern
turns the holdout into just another validation fold.

## Decision

The last 15% of the series is a protected holdout. `HoldoutGuard`
(`backtesting/walk_forward.py`) releases it only with explicit
`consume(confirm=True)`; a second release with the same data hash raises
unless `force_rerun=True`, and every release is recorded in
`runs/holdout_used.json` with data and config hashes. The only entry point
is `scripts/run_holdout.py`, which accepts a local CSV and never fetches
market data. Holdout execution is an operational action, not part of the
routine test suite.

## Consequences

- Accidental or repeated holdout peeking is blocked by default; deliberate
  reruns are auditable via the state file.
- `tests/unit/backtesting/test_walk_forward.py` covers the guard mechanics
  (confirm/force/rerun semantics) and the no-leakage invariants on synthetic
  sequences — never on real holdout data.
- Cost: evaluating a new idea against the holdout requires a conscious,
  logged operator decision. That friction is the point.
