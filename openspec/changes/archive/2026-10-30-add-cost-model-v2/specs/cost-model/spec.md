# Capability: cost-model

## ADDED Requirements

### Requirement: Cost profile

The system SHALL represent the cost assumptions of one execution model as a
frozen `CostProfile` with a non-empty `version`, maker and taker fee rates,
a liquidity label per leg, a slippage rate per leg, a funding rate per
period with its period length, and a maximum volume participation. The
profile SHALL reject a non-finite or out-of-range value, an unknown
liquidity label, and an empty version with `ValueError`.

#### Scenario: A valid profile is accepted

- WHEN a profile is built from the documented defaults
- THEN every field holds its value and no error is raised

#### Scenario: An unknown liquidity label is rejected

- WHEN a profile sets `entry_liquidity` to `"auction"`
- THEN `ValueError` is raised

#### Scenario: A strict mapping rejects unknown keys

- WHEN a profile is built from a mapping that contains an unknown key
- THEN `ValueError` is raised

### Requirement: Per-leg cost and R multiple

The net R multiple SHALL charge the entry fee and slippage on the entry
notional, the exit fee and slippage on the exit notional, and the funding
accrued over the holding time, and SHALL scale the result by the fill
fraction.

#### Scenario: The legacy profile reproduces the previous formula

- GIVEN a legacy report profile whose fee and slippage apply to both legs
- WHEN the net R multiple is computed for a resolved record
- THEN it matches the previous `net_r_multiple` formula to a relative error
  below `1e-12`

#### Scenario: A partial fill scales the R multiple

- GIVEN a trade whose fill fraction is `0.5`
- WHEN the net R multiple is computed
- THEN it equals half the fully filled value

#### Scenario: Funding grows with the holding time

- GIVEN a profile with a positive funding rate
- WHEN the holding time doubles
- THEN the funding part of the cost doubles

#### Scenario: An unknown exit reason is rejected

- WHEN the cost is computed for an exit reason other than `target`, `stop`
  or `expired`
- THEN `ValueError` is raised

### Requirement: Partial fill fraction

The system SHALL compute the fill fraction as the smaller of one and the
maximum participation times the quote volume divided by the notional. A
zero fraction SHALL mean the order does not fill. The quote volume of a
candle SHALL be its volume times its close.

#### Scenario: A deep book fills completely

- WHEN the quote volume is larger than the notional divided by the
  participation cap
- THEN the fill fraction is `1`

#### Scenario: A thin book fills partially

- WHEN the quote volume is half of the notional divided by the cap
- THEN the fill fraction is `0.5`

#### Scenario: A non-positive notional is rejected

- WHEN the notional is zero or negative
- THEN `ValueError` is raised

### Requirement: Simulator v2 with a frozen legacy branch

The event-driven simulator SHALL accept an optional cost profile. When the
profile version is the legacy simulator version the existing code path
SHALL run unchanged; any other version SHALL charge the v2 cost and count a
zero-fill trade as skipped.

#### Scenario: The legacy branch is unchanged

- GIVEN the legacy simulator profile
- WHEN the simulator runs on the fixture
- THEN it produces the same trades as before the change

#### Scenario: The v2 branch charges the model

- GIVEN a v2 profile
- WHEN the simulator resolves a trade
- THEN its R multiple matches `net_r` on the same inputs

#### Scenario: A zero fill is counted

- GIVEN a v2 profile and a bar whose quote volume yields a zero fill
- WHEN the simulator runs
- THEN the trade is skipped and `RunStats.skipped_unfilled` increases
