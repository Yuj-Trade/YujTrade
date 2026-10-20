# Proposal: add-paper-performance-report

## Why

The paper trading path cannot be audited. `SignalTracker` keeps a boolean
outcome per signal and prunes resolved entries older than
`signal_history_ttl_days` (30 by default), so the tracker is a moving
window, not a record of what happened. `TradingService._decide_expired_outcome`
falls back to the *current* market price when neither the stop nor the target
was touched inside the expiry window, which makes the recorded exit price and
exit time depend on when the reconciliation job happened to run. The three
metric helpers in `common/utils.py` (`calculate_sharpe_ratio`,
`calculate_sortino_ratio`, `calculate_max_drawdown`) have no caller, no test
and wrong formulas: Sharpe annualises per-signal returns with `sqrt(252)`,
Sortino measures dispersion only around the negative subset and returns
`inf` (invalid JSON) when there is no loss, and the drawdown helper consumes
a close-price frame instead of an equity curve. There is no verifiable
performance report for the paper book.

## What

1. An append-only `signal_resolutions` table in the existing paper ledger
   (`runs/paper_ledger.db`) that stores, for every reconciled signal, the
   exit reason (`stop`, `target`, `expired`, `no_data`), the exit price, the
   exit candle time, the number of candles used and the resolver version.
   `UPDATE` and `DELETE` on that table are rejected by triggers.
2. A pure resolution contract in `domain/` that resolves a signal against a
   candle window with an explicit *coverage* requirement, so an exit price is
   only produced when the window is fully observed. The current-price
   fallback is removed; a signal whose window is not covered resolves to
   `no_data` and keeps its exit price and exit time `NULL`.
3. Pure metric primitives in `domain/performance.py`: net R multiple,
   fixed-fraction return, equity curve, daily return series, maximum
   drawdown with peak/trough, Sharpe, Sortino, win rate, profit factor and
   expectancy. Standard library only, no `now()`, no I/O.
4. An application-level report builder (`application/performance_report.py`)
   that turns a list of resolution records plus a `PerformanceConfig` into a
   deterministic `PerformanceReport` with `data_hash` and `config_hash`.
5. Configuration, service, Telegram and script wiring:
   `ConfigManager.DEFAULT_CONFIG` gains the performance keys, the
   `TradingService` owns a `PaperLedger` and exposes
   `build_performance_report(as_of)`, `/performance` shows the new numbers,
   and `scripts/generate_performance_report.py` writes a JSON report.
6. Removal of the three unused metric helpers from `common/utils.py`.

**BREAKING**: the expired-signal resolution path changes behaviour. A signal
that expired without touching stop or target is no longer valued at the
current market price; it is valued at the close of the last candle inside
the expiry window, or marked `no_data` when the window is not covered. The
`SignalTracker` boolean outcome for such a signal is derived from the
resolved exit price against the entry, exactly as before, but the price
itself is no longer time-dependent.

## Non-goals

- Live execution, real-money risk, or any change to `execution_dry_run`.
- Signal generation, indicator construction, gate thresholds, `LONG_TERM_CONFIG`
  values, model training, artifacts, or the holdout protocol.
- Rewriting `scripts/run_holdout.py`; its Sharpe definition stays as it is and
  is registered as an open issue with a separate proposal suggested.
- A partial-fill model, a position-level equity curve, or per-symbol
  attribution. Overlapping trades are compounded sequentially.
- Backfilling the legacy tracker records that were resolved with the old
  pre-phase-3 logic. They are not in the ledger and are not in the report.
- Any scheduler, automatic delivery, or new Telegram command beyond
  `/performance`.

## Owner decisions (fixed)

| Decision | Value |
|---|---|
| Sizing | fixed fraction of equity from `risk_per_trade_pct`; one R risked |
| Initial equity | `initial_cash`, default `10000` |
| Cost | `paper_fee_rate = 0.001`, `paper_slippage_rate = 0.0005` (from `ConfigManager`) |
| Risk-free rate | `performance_rf_annual = 0` |
| Annualisation | `performance_periods_per_year = 365` |
| Expired trades | valued at the close of the last candle up to expiry; `no_data` is reported separately and excluded from the metrics |
| Minimum sample | `performance_min_trades_for_ratios = 30` |

## Default definitions (applied unless the owner changes them)

- **Cost in R**: `c = (fee_rate + slippage_rate) * (entry + exit) / |entry - stop|`,
  `R_net = R_gross - c`. `R_gross` is `(exit - entry) / (entry - stop)` for a
  buy and `(entry - exit) / (stop - entry)` for a sell. The cost is charged on
  both legs, therefore both `entry` and `exit` appear in the formula.
- **Equity curve**: `E0 = initial_cash`; for each trade
  `r_i = R_net_i * risk_per_trade_pct / 100` and `E_i = E_(i-1) * (1 + r_i)`.
  Processing order is `exit_at_utc`, then `signal_id`.
- **Daily series**: UTC calendar day of `exit_at_utc`; the return of a day is
  the product of `(1 + r)` over the trades closed that day, minus one. Days
  without a trade have a zero return and are part of the series.
- **Report window**: from the UTC day of the first exit in the included data
  to the UTC day of `as_of`.
- **MDD**: computed on the trade-level equity curve. The output carries the
  depth, the peak time, the trough time, the peak index, the trough index and
  the duration expressed in number of trades.
- **Sharpe**: `(mean(R_d) - rf_d) / stdev(R_d, ddof=1) * sqrt(periods_per_year)`
  with `rf_d = rf_annual / periods_per_year`.
- **Sortino**: `(mean(R_d) - rf_d) / DD * sqrt(periods_per_year)` with
  `DD = sqrt(sum(min(R_d - rf_d, 0)^2) / N)` where `N` is the number of days in
  the whole window, not only the losing ones.
- **Sample gate**: fewer closed trades than `min_trades_for_ratios` means the
  status is `insufficient_sample` and Sharpe and Sortino are `null`.
- **Undefined ratio**: a zero or undefined denominator yields `null` for that
  ratio; the report status stays `ok` or `insufficient_sample`.
- **Win**: `R_net > 0`. `profit_factor = sum(positive R) / |sum(negative R)|`
  and is `null` without losses. `expectancy_R = mean(R_net)`.
- **Overlapping trades** are compounded sequentially. This approximation is
  registered in the ADR and in `docs/open_issues.md`.
- **Determinism**: no `now()` in `domain/` or `application/`; the only clock
  input is `as_of`.
- **Rounding** happens in the display layer only; the internal values stay
  full precision.
- **JSON output** never contains `NaN` or `inf`; an undefined value is `null`.
- **`no_data` is final** and is never re-resolved, so the report is
  reproducible.

## Data contracts

### Exit reasons

| Reason | Condition | Exit price | Exit time |
|---|---|---|---|
| `stop` | the stop was touched in the window | the stop price | the candle time |
| `target` | the target was touched in the window | the target price | the candle time |
| `expired` | neither was touched and the coverage is complete | the close of the last candle at or before expiry | that candle time |
| `no_data` | the coverage is incomplete or no data exists | `NULL` | `NULL` |

When the stop and the target are touched in the same candle the stop wins
(ADR-0002). The current market price is never used as an exit price.

### Coverage

For the window `[created_at, end_at]` with `end_at = created_at + expiry_hours`:

- the first candle must not be later than `created_at + candle_duration`;
- the last candle must be such that its end is at or after `end_at`;
- the number of requested candles is derived from the expiry and the candle
  duration, not a fixed constant.

The candle duration per timeframe is read from `common/constants.py`; an
unknown timeframe is an explicit error.

### Time format

All timestamps are UTC and use `%Y-%m-%dT%H:%M:%S.%f+00:00` (microseconds are
always written), so lexicographic order equals chronological order.

### `signal_resolutions` schema

`id` (autoincrement primary key), `signal_id` (unique, not null), `symbol`,
`timeframe`, `side` (`buy`/`sell`), `entry`, `stop`, `target`,
`created_at_utc`, `exit_at_utc` (`NULL` for `no_data`), `exit_price` (`NULL`
for `no_data`), `exit_reason` (`stop`/`target`/`expired`/`no_data`),
`candles_used` (`>= 0`), `resolver_version`, `recorded_at_utc`. `CHECK`
constraints restrict `side` and `exit_reason` and enforce that
`exit_reason = 'no_data'` holds exactly when `exit_price` and `exit_at_utc`
are `NULL`. Triggers reject `UPDATE` and `DELETE`.

### Tracker details

`symbol`, `timeframe`, `signal_type`, `entry`, `stop`, `target`, `created_at`,
`candle_time`, plus `resolved_price`, `resolution_source` and `resolved_at`
once resolved. The tracker key is `target`, not `exit_price`.

## Configuration keys

`ConfigManager.DEFAULT_CONFIG` gains:

| Key | Default |
|---|---|
| `performance_ledger_enabled` | `False` |
| `paper_fee_rate` | `0.001` |
| `paper_slippage_rate` | `0.0005` |
| `performance_rf_annual` | `0` |
| `performance_periods_per_year` | `365` |
| `performance_min_trades_for_ratios` | `30` |
| `risk_per_trade_pct` | existing value (1.0, unchanged) |
| `initial_cash` | existing value (10000, unchanged) |

## Affected files

| Path | Change |
|---|---|
| `domain/performance.py` | new: `ResolutionRecord` and the pure metric primitives |
| `domain/outcome.py` | new: full-coverage resolution function (`resolve_outcome` unchanged) |
| `application/performance_report.py` | new: `PerformanceConfig`, `PerformanceReport`, report builder |
| `trading/ledger.py` | `signal_resolutions` table, triggers, `record_resolution`, `has_resolution`, `load_resolutions` |
| `services/trading_service.py` | resolution via the domain, ledger write, `build_performance_report` |
| `strategy/signal_tracker.py` | `no_data` handling, `resolution_status`, summary key |
| `config/settings.py` | performance defaults |
| `trading/paper_trading.py` | `fee_rate`/`slippage_rate` from the configuration |
| `common/constants.py` | candle duration per timeframe |
| `app/telegram_bot.py` | extended `/performance` output |
| `scripts/generate_performance_report.py` | new: JSON report generator |
| `common/utils.py` | the three unused metric helpers removed |
| `docs/adr/ADR-0009-performance-metrics.md` | new ADR (ADR-0008 is taken) |
| `docs/performance-worked-example.md` | new: worked example |
| `docs/architecture.md`, `docs/runbook.md`, `docs/open_issues.md` | updated |

## Risks and rollback

- **Behaviour change in the resolution path**: mitigated by characterization
  tests in phase 1, dedicated tests in phase 3 and the `[behavior-change]`
  tag on the commit. Rollback is a revert of that single commit.
- **Coverage can fail often**: the market data provider only supports a
  candle *count*, not a time range, so a signal reconciled late may not have
  its window covered and becomes `no_data`. The `no_data` ratio is a
  monitored acceptance criterion; a rising ratio means the reconciliation
  cadence has to move closer to the expiry.
- **Ledger growth**: the table is append-only and is never pruned. The volume
  is one row per reconciled signal.
- **`performance_ledger_enabled` stays `false` in the committed defaults**;
  it is enabled in the local runtime configuration only after the soak.
- **Concurrency**: SQLite is a single writer (ADR-0004). The ledger write is
  awaited in the reconciliation loop, so it serialises with the order path.

## Rollback plan

The flag `performance_ledger_enabled` disables the ledger write; the report
builder then reports an empty ledger. The resolution behaviour change is
reverted by reverting the phase-3 commit. The `signal_resolutions` table is
left in place: it is append-only and inert when the flag is off.
