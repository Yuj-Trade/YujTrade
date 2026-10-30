# ADR-0009: Paper performance metrics

Status: accepted.

## Context

The paper book could not be audited. `SignalTracker` keeps a boolean
outcome per signal, prunes the resolved entries after
`signal_history_ttl_days` and rotates the overflow, so it is a moving
window rather than a record. The expired-signal resolution fell back to
the current market price, which made the recorded exit price and exit
time depend on when the reconciliation job happened to run. The three
metric helpers in `common/utils.py` had no caller, no test and wrong
formulas.

This ADR fixes the definitions, the decisions and the limitations of the
verifiable performance report. The proposal is
`openspec/changes/add-paper-performance-report`; the worked example with
the full arithmetic is `docs/performance-worked-example.md`.

Note on the number: the directive named this document
`ADR-0008-performance-metrics.md`, but ADR-0008 is already taken by
`ADR-0008-model-lifecycle.md`. The next free number is used instead.

## Decision

### Data source

The report is built from the append-only `signal_resolutions` table of the
paper ledger (`runs/paper_ledger.db`). The tracker is not a source: it is
TTL-bounded, rotated and holds a boolean outcome only.

### Exit reasons

| Reason | Condition | Exit price | Exit time |
|---|---|---|---|
| `stop` | the stop was touched in the window | the stop price | the candle time |
| `target` | the target was touched in the window | the target price | the candle time |
| `expired` | neither was touched and the coverage is complete | the close of the last candle at or before the expiry | that candle time |
| `no_data` | the coverage is incomplete or no data exists | `NULL` | `NULL` |

The stop wins when one candle touches both levels (ADR-0002). The current
market price is never used as an exit price. The resolution window starts
at `created_at`, the moment the signal was registered, and not at the
signal candle time; this keeps the live path aligned with
`domain/outcome.py`.

### Coverage

For the window `[created_at, end_at]` with `end_at = created_at +
expiry_hours`, the coverage is complete when the first window candle is
not later than `created_at + candle_duration` and the last window candle
ends at or after `end_at`. The number of requested candles is
`ceil(expiry_hours / candle_duration) + 2`, derived from the expiry and
the candle duration instead of a fixed constant. The candle duration per
timeframe is read from `common/constants.py`; an unknown timeframe is an
explicit error.

### Cost model

```
cost_R = (fee_rate + slippage_rate) * (entry + exit) / |entry - stop|
R_net  = R_gross - cost_R
R_gross(buy) = (exit - entry) / (entry - stop)
R_gross(sell) = (entry - exit) / (stop - entry)
```

The cost is charged on both legs, therefore both `entry` and `exit` appear
in the formula. `fee_rate` is `paper_fee_rate` and `slippage_rate` is
`paper_slippage_rate`; both come from `ConfigManager`.

### Sizing and equity

Fixed fraction of the equity: one R is risked per trade and
`risk_per_trade_pct` decides the fraction.

```
r_i = R_net_i * risk_per_trade_pct / 100
E_0 = initial_cash
E_i = E_(i-1) * (1 + r_i)
```

The processing order is `exit_at_utc`, then `signal_id`.

### Daily series

The UTC calendar day of `exit_at_utc` groups the trades. The return of a
day is the product of `(1 + r)` over the trades closed that day, minus
one. A day without a trade has a zero return and is part of the series.
The report window runs from the UTC day of the first exit to the UTC day
of `as_of`.

### Ratios

```
rf_d   = rf_annual / periods_per_year
Sharpe = (mean(R_d) - rf_d) / stdev(R_d, ddof=1) * sqrt(periods_per_year)
DD     = sqrt(sum(min(R_d - rf_d, 0)^2) / N)
Sortino = (mean(R_d) - rf_d) / DD * sqrt(periods_per_year)
```

`N` is the number of **all** days in the window, not only the losing
ones. Fewer closed trades than `performance_min_trades_for_ratios` yields
the status `insufficient_sample` with `null` ratios. A zero or undefined
denominator yields `null` for that ratio; the status stays `ok` or
`insufficient_sample`.

### Drawdown

The maximum drawdown is computed on the trade-level equity curve and
reports the depth, the peak index and time, the trough index and time and
the duration expressed in number of trades.

### Trade statistics

A win is `R_net > 0`.
`profit_factor = sum(positive R) / |sum(negative R)|` and is `null`
without losses. `expectancy_R = mean(R_net)`.

### Determinism

`domain/` and `application/` never read the clock; the only clock input is
`as_of`. Rounding happens in the display layer only. The JSON output never
contains `NaN` or `inf`; an undefined value is `null`. The `data_hash` is
the SHA-256 of the canonical JSON of the included records (including the
`no_data` rows) in the canonical order and the `config_hash` is the
SHA-256 of the effective parameters. A `no_data` resolution is final and
is never re-resolved.

## Consequences

- The report is reproducible: the same ledger and the same configuration
  always produce the same `data_hash` and the same numbers, and an
  independent calculator reproduces them to a relative difference below
  `1e-9`.
- The metrics live in `domain/performance.py` and
  `application/performance_report.py`; the service only loads the data and
  delegates, and the script and the Telegram command are display layers.
- `performance_ledger_enabled` is `false` in the committed defaults. The
  flag is only turned on in the local runtime configuration after the
  fourteen-day soak.

## Limitations

- **Overlapping trades are compounded sequentially.** The equity curve
  assumes the trades do not overlap in capital. A position-level or
  concurrent-exposure model is not implemented.
- **Legacy resolutions are not part of the report.** The signals that the
  tracker resolved with the pre-phase-3 logic are not written to the
  ledger and are not backfilled, because backfilling them would require
  re-running the non-reproducible current-price fallback.
- **The data provider only supports a candle count, not a time range.**
  The resolver therefore asks for a derived count and verifies the
  coverage itself. A signal reconciled later than its expiry can fail the
  coverage check and become `no_data`; the `no_data` ratio is a monitored
  acceptance criterion of the soak.
  *Superseded 2026-10-29 (`870d0c4`): `fetch_ohlcv_range` fetches the
  window by time, so the request size no longer decides coverage.*
- **The `1M` candle duration is a fixed 43200 minutes** (30 days) because
  a calendar month has no fixed length, so the monthly coverage check is
  approximate.
- **The cost model is flat and per trade.** There is no partial fill
  model, no funding cost, no slippage model beyond the constant rate and
  no maker/taker distinction. `PaperTradingEngine` uses the same two
  rates, so the report and the paper engine agree on the cost.
- **The equity curve is a model, not the paper portfolio.** The report
  compounds fixed fractions of the equity; the paper engine sizes its
  positions with a risk model and a portfolio exposure cap. The two are
  deliberately not reconciled in this phase.
- **The Sharpe in `scripts/run_holdout.py` is a different quantity.** It
  divides the mean pnl by `pstdev(pnl)` and multiplies by the square
  root of the trade count, without an annualisation and without a
  risk-free rate. The holdout report schema is locked and the holdout
  protocol is single-use, so the holdout path is left untouched and the
  divergence is registered in `docs/open_issues.md`.

## Amendment 2026-10-29 (P6)

### One implementation

The formulas above now have one implementation,
`domain/performance.py:summarize_closed_trades`, which consumes
`ClosedTrade` values (`exit_at`, `signal_id`, `return_fraction`).
`fractions_from_pnl` converts a currency PnL series into return fractions
against a sequential equity and raises when a trade drives the equity to
zero or below. Every consumer uses it: the performance report, the paper
portfolio summary (`application/performance_report.py:build_portfolio_summary`),
the historical trade metrics, the holdout script and the walk-forward
script. `backtesting/historical_signals.py:trade_metrics` keeps its legacy
keys and returns `None` where a ratio is undefined.

### Two labelled equity views

The report equity, which compounds fixed fractions of the model, and the
paper portfolio equity, which compounds the executed positions, stay two
views. The report carries `equity_source: "signal_model"`; the paper
portfolio summary carries `equity_source: "paper_portfolio"`. When the same
R outcomes feed both, the Sharpe, the Sortino, the drawdown depth and the
final equity agree within `1e-9`
(`tests/unit/application/test_metrics_parity.py`).

### Legacy exclusion

Resolutions recorded before the phase-3 resolver stay excluded and are not
backfilled. The report carries the fixed note
`legacy_resolutions_note` and a `coverage` block:

```json
{
  "legacy_resolutions_included": false,
  "legacy_full_fill_records": 0,
  "unfilled_trades": 0
}
```

`legacy_full_fill_records` counts the rows without an entry quote volume
(treated as a full fill); `unfilled_trades` counts the rows whose fill
fraction is `0.0` (excluded from every statistic).

### Cost model

The cost section above describes the legacy report profile, which is still
the default when no profile is supplied. The cost-model-v2 profile adds
per-leg maker/taker fees, per-leg slippage, close-time funding and a
partial fill; see `docs/performance-worked-example-v2.md`.
