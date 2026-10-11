# ADR-0002: Live and backtest parity

Status: accepted.

## Context

A backtest that resolves exits differently from the live path produces
Sharpe numbers that cannot be trusted. The two most common divergences are
stop/target priority and gap handling at the exit bar.

## Decision

Exit resolution has exactly one implementation: `domain.outcome.resolve_outcome`
(stop-first, then target, per candle, with optional creation/expiry window).
`EventDrivenSimulator` calls it for every signal (`backtesting/simulator.py`);
the live/paper path resolves through the same function. The simulator adds
only market friction on top: entry at the next bar open with slippage, gap
override when the exit bar opens beyond the stop, commission on entry plus
exit. Candle shape (`open/high/low/close/timestamp`) and signal parameters
(`side/entry/stop/target`) are the shared contract.

## Consequences

- Any change to exit semantics lands in one function and is covered by
  `tests/unit/domain/test_outcome_edges.py` plus the simulator/parity tests.
- Simulation stays honest about costs (commission, slippage) without
  reimplementing resolution.
- Cost: the simulator cannot express fills that the domain function cannot
  describe (e.g. partial fills need a separate, explicit model).
