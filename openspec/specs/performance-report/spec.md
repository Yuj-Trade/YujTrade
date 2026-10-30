# performance-report Specification

## Purpose
TBD - created by archiving change unify-performance-metrics. Update Purpose after archive.
## Requirements
### Requirement: Unified closed-trade metrics

`domain/performance.py` SHALL compute the Sharpe ratio, the Sortino ratio and
the maximum drawdown from one closed-trade series, and every consumer SHALL
use those functions. A closed trade SHALL carry its exit instant, its signal
id and its return fraction. A currency PnL series SHALL be converted to
return fractions against a sequential equity.

#### Scenario: A currency PnL series becomes return fractions

- GIVEN a list of trades with currency PnL and an initial equity
- WHEN the fractions are computed
- THEN each fraction is its PnL divided by the equity before the trade and
  the trades are processed by exit time and signal id

#### Scenario: A wipe-out is rejected

- GIVEN a trade whose PnL drives the equity to zero or below
- WHEN the fractions are computed
- THEN `ValueError` is raised

#### Scenario: An empty sample has no ratios

- GIVEN no closed trade
- WHEN the summary is built
- THEN the ratios are `None` and the status says the sample is empty

#### Scenario: An insufficient sample has no ratios

- GIVEN fewer trades than the minimum sample
- WHEN the summary is built
- THEN the status is `insufficient_sample` and the ratios are `None`

### Requirement: Historical trade metrics use the unified definitions

The historical trade metrics SHALL delegate to the domain and SHALL accept
the annualisation factor and the risk-free rate as keyword-only arguments. A
ratio with no losses in the denominator SHALL be `None`, never `0.0`. The
legacy keys SHALL be preserved.

#### Scenario: The keys are preserved

- WHEN the historical trade metrics are computed for a set of trades
- THEN the result holds `trades_count`, `win_rate`, `profit_factor`,
  `max_drawdown`, `sharpe` and `final_equity`

#### Scenario: No loss yields no profit factor

- GIVEN a trade list without a losing trade
- WHEN the metrics are computed
- THEN `profit_factor` is `None`

### Requirement: Holdout report schema v2

`scripts/run_holdout.py` SHALL write `schema_version: "holdout-v2"`. The
top-level `sharpe` SHALL be the unified value, the previous value SHALL be
kept as `sharpe_legacy_pnl`, a `metrics_v2` block SHALL hold `sortino` and
the drawdown depth and duration, and the report SHALL carry
`cost_model_version`, `periods_per_year` and `rf_annual`. A report without
`schema_version` SHALL be read as v1. The holdout SHALL stay single-use: the
state file is not touched by the schema change.

#### Scenario: A v2 report is produced

- GIVEN synthetic data, a temporary state file and `consume(confirm=True)`
- WHEN the holdout runs
- THEN the report carries `schema_version = "holdout-v2"`, the unified
  `sharpe`, `sharpe_legacy_pnl`, `metrics_v2` and `cost_model_version`

#### Scenario: A v1 report is still readable

- GIVEN a report without `schema_version`
- WHEN it is read
- THEN it is treated as v1

### Requirement: Two labelled equity views with a parity test

The report equity SHALL stay distinct from the paper portfolio equity as two
labelled views. Each view SHALL expose its own label; the report SHALL never
silently merge the two.
The report SHALL carry `equity_source: "signal_model"` and the paper
portfolio summary SHALL be labelled separately. When the same R outcomes are
fed to both, the ratios and the final equity SHALL agree within `1e-9`.

#### Scenario: The two views agree on the same outcomes

- GIVEN a set of R outcomes
- WHEN the report and the paper portfolio summary are built from them
- THEN the Sharpe, the Sortino, the drawdown depth and the final equity
  match within `1e-9`

### Requirement: Legacy resolution coverage

The report SHALL state that resolutions recorded before the phase-3 resolver
are excluded and are not backfilled, and SHALL carry a `coverage` block that
counts the legacy full-fill records and the unfilled trades.

#### Scenario: The exclusion is stated

- WHEN a report is built
- THEN it carries the legacy exclusion note and the coverage counts

