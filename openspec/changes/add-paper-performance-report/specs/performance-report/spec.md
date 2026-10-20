# Capability: performance-report

## ADDED Requirements

### Requirement: Append-only resolution ledger

The paper ledger SHALL store one immutable row per reconciled signal in a
`signal_resolutions` table with the columns `id`, `signal_id`, `symbol`,
`timeframe`, `side`, `entry`, `stop`, `target`, `created_at_utc`,
`exit_at_utc`, `exit_price`, `exit_reason`, `candles_used`,
`resolver_version` and `recorded_at_utc`. The table SHALL reject `UPDATE` and
`DELETE`. The existing `orders`, `fills`, `positions` and `equity_snapshots`
tables SHALL keep their current behaviour.

#### Scenario: First resolution is stored

- GIVEN an empty paper ledger
- WHEN a resolution for `signal_id = "sig-1"` is recorded
- THEN the row is written and the method returns `True`

#### Scenario: Duplicate signal id is rejected without an error

- GIVEN a resolution for `signal_id = "sig-1"` is already stored
- WHEN a second resolution with the same `signal_id` is recorded
- THEN the method returns `False`, the first row is unchanged and the row
  count stays `1`

#### Scenario: A check violation is raised

- GIVEN a resolution whose `exit_reason` is `stop` but whose `exit_price` is
  `NULL`
- WHEN it is recorded
- THEN the database raises an integrity error and no row is written

#### Scenario: Update and delete are rejected

- GIVEN a stored resolution
- WHEN an `UPDATE` or a `DELETE` is issued against `signal_resolutions`
- THEN the database raises an append-only error

#### Scenario: Timestamps use the fixed format

- GIVEN a resolution created at `2026-10-01T10:00:00+00:00` and resolved at
  `2026-10-01T14:00:00+00:00`
- WHEN it is stored
- THEN `created_at_utc` and `exit_at_utc` are written as
  `2026-10-01T10:00:00.000000+00:00` and `2026-10-01T14:00:00.000000+00:00`

#### Scenario: No data resolution stores null exit fields

- GIVEN a resolution with `exit_reason = "no_data"`
- WHEN it is stored
- THEN `exit_price` and `exit_at_utc` are `NULL`

#### Scenario: Initialising twice keeps the rows

- GIVEN a ledger that already holds a resolution
- WHEN `initialize` runs twice
- THEN the stored row is still there and no error is raised

### Requirement: Deterministic full-coverage resolution

The system SHALL resolve a signal against a candle window only when the
window is fully observed. The exit reason SHALL be one of `stop`, `target`,
`expired` or `no_data`. The current market price SHALL never be used as an
exit price. The number of requested candles SHALL be derived from the expiry
and the candle duration instead of a fixed constant, and an unknown
timeframe SHALL raise an explicit error.

#### Scenario: The stop is touched

- GIVEN a buy signal whose stop is touched inside the window
- WHEN the signal is resolved
- THEN the exit reason is `stop`, the exit price is the stop price and the
  exit time is the time of that candle

#### Scenario: The target is touched

- GIVEN a buy signal whose target is touched inside the window
- WHEN the signal is resolved
- THEN the exit reason is `target`, the exit price is the target price and
  the exit time is the time of that candle

#### Scenario: The stop wins inside one candle

- GIVEN a candle whose range contains both the stop and the target
- WHEN the signal is resolved
- THEN the exit reason is `stop`

#### Scenario: The window expires without a hit

- GIVEN a fully covered window in which neither the stop nor the target is
  touched
- WHEN the signal is resolved
- THEN the exit reason is `expired`, the exit price is the close of the last
  candle at or before the expiry and the exit time is that candle time

#### Scenario: The coverage is incomplete

- GIVEN a window whose first candle starts after `created_at` plus one
  candle duration, or whose last candle ends before the expiry
- WHEN the signal is resolved
- THEN the exit reason is `no_data` and the exit price and the exit time are
  `NULL`

#### Scenario: The stop and the target outcomes match the previous contract

- GIVEN the same candle sequence and the same levels
- WHEN the new resolver and the previous outcome resolver run
- THEN both report the same exit price and the same success flag for the
  `stop` and the `target` cases

### Requirement: Ledger write ordering during reconciliation

When the performance ledger is enabled the system SHALL resolve the signal
first, skip the write when a resolution for that `signal_id` already exists,
otherwise record the resolution, and SHALL keep the signal pending when the
record fails. The tracker SHALL be synchronised afterwards.

#### Scenario: An existing resolution is not written twice

- GIVEN a ledger that already holds a resolution for the signal
- WHEN the signal is reconciled
- THEN no second row is written and the tracker is synchronised

#### Scenario: A ledger error keeps the signal pending

- GIVEN a ledger write that raises an error
- WHEN the signal is reconciled
- THEN the error is logged, the tracker outcome is not written and the
  signal stays pending for the next cycle

#### Scenario: A no-data resolution never writes a boolean outcome

- GIVEN a signal that resolves to `no_data`
- WHEN the tracker is synchronised
- THEN the tracker keeps the outcome unset and stores
  `resolution_status = "no_data"`

#### Scenario: A no-data signal is not reconciled again

- GIVEN a tracker entry whose `resolution_status` is `no_data`
- WHEN the pending expired entries are listed
- THEN the entry is not returned

### Requirement: Pure performance metrics

`domain/performance.py` SHALL provide the net R multiple, the fixed-fraction
return, the equity curve, the daily return series, the maximum drawdown with
its peak and trough, the Sharpe ratio, the Sortino ratio, the win rate, the
profit factor and the expectancy. The module SHALL use the standard library
only, SHALL perform no I/O, SHALL not read the clock, SHALL reject `NaN` and
`inf` inputs with a `ValueError` and SHALL return `None` for an undefined
result.

#### Scenario: The net R multiple subtracts the round-trip cost

- GIVEN a buy from `100` with a stop at `90` and an exit at `120`
- WHEN the net R multiple is computed with a fee rate of `0.001` and a
  slippage rate of `0.0005`
- THEN it equals `2 - (0.001 + 0.0005) * (100 + 120) / 10`

#### Scenario: The equity curve compounds the fractions

- GIVEN an initial equity of `1000` and the fractions `[0.1, -0.05]`
- WHEN the equity curve is built
- THEN it equals `[1000.0, 1100.0, 1045.0]`

#### Scenario: The daily series keeps the idle days

- GIVEN two trades closed on the same day and an empty following day
- WHEN the daily returns are built over a three-day window
- THEN the series is `[0.21, 0.0, 0.0]`

#### Scenario: The drawdown reports the peak and the trough

- GIVEN the equity curve `[100, 120, 90, 110, 80]`
- WHEN the maximum drawdown is computed
- THEN the depth is `1/3`, the peak index is `1`, the trough index is `4` and
  the duration is `3` trades

#### Scenario: The Sortino denominator uses every day

- GIVEN four daily returns of which one is negative
- WHEN the Sortino ratio is computed
- THEN the downside deviation is divided by the number of all four days

#### Scenario: An undefined ratio is `None`

- GIVEN a constant return series with a zero spread
- WHEN the Sharpe ratio is computed
- THEN the result is `None` and no `inf` is produced

#### Scenario: A non-finite input is rejected

- GIVEN a return series that contains `NaN`
- WHEN the Sharpe ratio is computed
- THEN a `ValueError` is raised

### Requirement: Deterministic performance report

`application/performance_report.py` SHALL build a `PerformanceReport` from a
list of resolution records, a `PerformanceConfig` and an `as_of` instant. The
report SHALL carry the version, the mode, the daily window, the status, the
resolved count, the count per exit reason, the win rate, the profit factor,
the expectancy, the initial and final equity, the total return, the maximum
drawdown, the Sharpe and Sortino ratios, the effective parameters, the
`data_hash` and the `config_hash`. The application layer SHALL NOT depend on
`ConfigManager` and SHALL NOT read the clock.

#### Scenario: No trade

- GIVEN an empty list of records
- WHEN the report is built
- THEN the status is `no_trades`, the ratios are `None` and the equity is
  the initial equity

#### Scenario: Only no-data records

- GIVEN a list that contains only `no_data` records
- WHEN the report is built
- THEN the status is `no_trades`, the `no_data` count is reported and the
  metrics stay empty

#### Scenario: A single trade

- GIVEN one resolved trade
- WHEN the report is built
- THEN the status is `insufficient_sample`, the Sharpe and the Sortino are
  `None` and the equity curve has one step

#### Scenario: The report does not depend on the input order

- GIVEN the same records in two different orders
- WHEN two reports are built
- THEN they carry the same `data_hash` and the same metric values

#### Scenario: A changed record changes the hash

- GIVEN two record sets that differ in a single exit price
- WHEN two reports are built
- THEN the `data_hash` values differ

#### Scenario: The JSON output is valid

- GIVEN a report that contains an undefined ratio
- WHEN it is serialised to JSON
- THEN the output contains `null` and contains neither `NaN` nor `inf`

### Requirement: Performance configuration

`ConfigManager.DEFAULT_CONFIG` SHALL provide `performance_ledger_enabled`,
`paper_fee_rate`, `paper_slippage_rate`, `performance_rf_annual`,
`performance_periods_per_year` and `performance_min_trades_for_ratios`.
`risk_per_trade_pct` and `initial_cash` SHALL keep their current values.
`PaperTradingEngine` SHALL take its fee and slippage rates from the
configuration instead of hard-coded constructor defaults.

#### Scenario: The defaults are present

- GIVEN a configuration without a runtime override file
- WHEN the effective configuration is read
- THEN every performance key is present with its documented default

#### Scenario: The committed defaults keep paper mode

- GIVEN the committed `ConfigManager.DEFAULT_CONFIG`
- WHEN `performance_ledger_enabled` is read
- THEN it is `False` and no live execution path is enabled

#### Scenario: The paper engine uses the configured rates

- GIVEN a configuration with `paper_fee_rate` and `paper_slippage_rate`
- WHEN a `PaperTradingEngine` is built from it
- THEN the engine uses those rates and the constructor has no hard-coded
  default for them

### Requirement: Report delivery

The Telegram `/performance` command SHALL keep its current lines and add the
trade count, the win rate, the profit factor, the expectancy, the total
return, the maximum drawdown, the Sharpe and Sortino ratios, the status, the
`no_data` count and the first eight characters of the `data_hash`. The
message SHALL be escaped with `escape_markdown_v2` and SHALL stay below 4096
characters. The command SHALL remain administrator-only. The script
`scripts/generate_performance_report.py` SHALL accept an `as_of` instant and
an output path, SHALL write the JSON report under `runs/performance/` and
SHALL print the `data_hash`.

#### Scenario: The command reports the new numbers

- GIVEN a service that returns a performance report
- WHEN an administrator runs `/performance`
- THEN the message contains the status, the drawdown, the Sharpe, the
  Sortino and the short `data_hash`

#### Scenario: A non-administrator is rejected

- GIVEN a non-administrator
- WHEN `/performance` is invoked
- THEN no message is sent

#### Scenario: The script writes a report

- GIVEN an `as_of` instant and an output path
- WHEN the script runs
- THEN a JSON report is written and the `data_hash` is printed

### Requirement: No metric logic outside the decision core

The metric and report logic SHALL live in `domain/` and `application/` only.
The service layer SHALL only load the data and delegate. No scheduling, no
automatic delivery and no new Telegram command SHALL be added.

#### Scenario: The service only delegates

- GIVEN a service with a paper ledger
- WHEN `build_performance_report` is called
- THEN the service loads the records and hands them to the application
  builder without computing a metric itself
