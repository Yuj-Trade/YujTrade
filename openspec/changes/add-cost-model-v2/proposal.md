# Proposal: add-cost-model-v2

Approval: approved by YT-IMPL-SPEC Revision 2.0 (2026-10-29), decision G1.

## Why

Three cost implementations disagree. The performance report charges
`(fee + slippage) * (entry + exit) / risk` on both legs, the event-driven
simulator hard-codes `commission_rate = 0.001` and `slippage_rate = 0.0005`
and applies slippage to the entry only, and the paper engine applies
slippage to entry fills only. None of them models a maker/taker
distinction, funding, or a partial fill, and the funding code in the paper
engine is never called.

## What Changes

- `domain/costs.py` gains a frozen `CostProfile`, `cost_per_unit`, `net_r`,
  `fill_fraction`, `first_candle_quote_volume`, `legacy_report_profile`,
  `legacy_simulator_profile` and `cost_profile_from_config`.
- The report charges per-leg maker/taker fees, per-leg slippage and
  close-time funding; a partial fill scales the R multiple.
- The paper engine follows the same cost model and records the fill
  fraction; the dead `apply_funding` / `funding_rate_per_day` are removed.
- The event-driven simulator gains a v2 branch that uses the profile, and
  the legacy branch is frozen so the existing golden stays byte-identical.
- `signal_resolutions` gains a nullable `entry_quote_volume` column.
- **BREAKING** for the report: `REPORT_VERSION` becomes
  `performance-report-v2` and the parameters list carries the profile.
  The legacy report profile reproduces the previous numbers exactly.

## Impact

- Affected specs: `cost-model`, `performance-report`
- Affected code: `domain/costs.py` (new), `domain/performance.py`,
  `domain/outcome.py`, `application/performance_report.py`,
  `trading/paper_trading.py`, `trading/ledger.py`,
  `backtesting/simulator.py`, `scripts/record_backtest.py`,
  `scripts/run_holdout.py`, `scripts/run_walk_forward.py`,
  `services/trading_service.py`, `config/settings.py`
- New golden: `tests/golden/backtest_cost_v2_baseline.json`; the two
  existing golden files stay byte-identical.
