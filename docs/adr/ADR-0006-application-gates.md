# ADR-0006: Application gates

Status: accepted.

## Context

The signal generator built an always-open gate (zero confidence floor, WEAK
trend floor, zero volume floor, unbounded score), logged the application
decision, and returned the signal anyway. The application layer therefore
controlled nothing, and rejected candidates still reached the service and
the backtest.

## Decision

Gate construction moves to `application/gate_config.py:build_gate_config`,
the single constructor both the generator and the service use, reading the
same keys and defaults the service always used. `generate_signal` uses the
real adaptive threshold as its score floor, normalizes confidence through
`domain/gates.py:normalize_confidence`, validates level geometry up front in
`application/decide.py`, and returns `None` for any rejection. Threshold
values stay frozen; fixtures were shaped to pass them.

## Consequences

- No rejected or invalid-level signal leaves the generator; the service gate
  and the generator gate agree by construction (parity test).
- Golden baselines were re-recorded once for this change (51 signals,
  15 trades) and are byte-stable since.
- Backtest-path scores are capped by design (disabled ML/external
  components contribute zero weight), so the confidence floor binds harder
  there than live; that asymmetry is intended and documented.
