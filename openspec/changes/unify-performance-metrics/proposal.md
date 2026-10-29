# Proposal: unify-performance-metrics

Approval: approved by YT-IMPL-SPEC Revision 2.0 (2026-10-29), decisions G1,
G7 and G8.

## Why

Two Sharpe definitions are in use for the same metric. The domain version is
annualised, uses daily returns, applies a risk-free rate and `ddof=1`; the
holdout path computes `mean(pnl) / pstdev(pnl) * sqrt(n)` with no
annualisation and no risk-free rate, and returns `profit_factor = 0.0` when
there are no losses. Every consumer (the report, the holdout, the
walk-forward script, the paper portfolio and `/performance`) computes its own
numbers, so the same book reports different ratios.

## What Changes

- `domain/performance.py` gains `ClosedTrade`, `PnlTrade`,
  `fractions_from_pnl`, `summarize_closed_trades` and `PerformanceSummary`;
  the ADR-0009 formulas live in one place.
- `trade_metrics` delegates to the domain and takes keyword-only
  `periods_per_year` and `rf_annual`.
- The holdout report becomes schema v2: the unified `sharpe`, the previous
  value kept as `sharpe_legacy_pnl`, a `metrics_v2` block and the cost
  model version.
- A parity test pins the report and the paper portfolio to the same
  fractions within `1e-9`.
- **BREAKING** for the holdout report schema: a report without
  `schema_version` is v1.

## Impact

- Affected specs: `performance-report`
- Affected code: `domain/performance.py`,
  `application/performance_report.py`,
  `backtesting/historical_signals.py`, `scripts/run_holdout.py`,
  `scripts/run_walk_forward.py`, `scripts/generate_performance_report.py`,
  `app/telegram_bot.py`, `tests/unit/backtesting/test_historical_signals.py`
- Amends ADR-0005 and ADR-0009.
