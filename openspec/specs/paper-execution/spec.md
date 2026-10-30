# paper-execution Specification

## Purpose
TBD - created by archiving change add-paper-execution-path. Update Purpose after archive.
## Requirements
### Requirement: Paper signal execution

`TradingService.execute_signal(signal, mode="paper")` SHALL accept only the
`paper` mode and SHALL never raise for a rejected request; it SHALL return a
result dictionary with `ok` and a `reason`. A request SHALL be refused when
the mode is unsupported, when the kill switch is off, when the signal
already has an order, when a mark price is missing, when the risk manager
rejects the size, or when the order does not fill.

#### Scenario: An accepted signal fills

- GIVEN an enabled paper path, a signal without an order, and a mark price
- WHEN the signal is executed
- THEN the result is `ok` with the order id, the position id, the filled
  quantity, the fill fraction, the fill price and the fee

#### Scenario: An unsupported mode is refused

- WHEN the mode is `live`
- THEN the result is not `ok` with reason `unsupported_mode` and no exception
  is raised

#### Scenario: The kill switch refuses execution

- GIVEN `paper_execution_enabled` is false
- WHEN a signal is executed
- THEN the result is not `ok` with reason `paper_execution_disabled`

#### Scenario: A duplicate signal is refused

- GIVEN the signal already has a persisted order
- WHEN the signal is executed again
- THEN the result is not `ok` with reason `duplicate_signal`

#### Scenario: A missing mark price is refused

- GIVEN an open position whose symbol has no price
- WHEN a signal is executed
- THEN the result is not `ok` with reason `no_mark_price`

#### Scenario: A risk rejection is refused

- GIVEN a size the risk manager rejects
- WHEN the signal is executed
- THEN the result is not `ok` with reason `risk_rejected`

#### Scenario: A zero fill is refused

- GIVEN a last candle whose quote volume yields a zero fill fraction
- WHEN the signal is executed
- THEN the result is not `ok` with reason `unfilled`

### Requirement: Paper position lifecycle persistence

The paper ledger SHALL hold the position lifecycle in append-only tables,
`paper_positions_opened` and `paper_positions_closed`, each rejecting
`UPDATE` and `DELETE`. Open positions SHALL be the opened rows minus the
closed rows, so a restart rehydrates them.

#### Scenario: A restart restores the open positions

- GIVEN an opened and unclosed position on disk
- WHEN a new service starts
- THEN the position is open in memory

#### Scenario: A closed position is not restored

- GIVEN a position that has a closing row
- WHEN a new service starts
- THEN the position is not open in memory

#### Scenario: The tables reject mutation

- WHEN an `UPDATE` or a `DELETE` is issued against either table
- THEN the database raises an append-only error

### Requirement: Paper position resolution

`TradingService.resolve_open_paper_positions(now)` SHALL fetch the candles
by range from the position open time and resolve the position through
`domain.outcome`. A `no_data` resolution SHALL keep the position open and
mark it stale; a closed resolution SHALL be appended to
`paper_positions_closed`.

#### Scenario: A target closes the position

- GIVEN an open long position whose window touches the target
- WHEN the positions are resolved
- THEN the closing row records the target exit

#### Scenario: A no-data window keeps the position open

- GIVEN a window without coverage
- WHEN the positions are resolved
- THEN the position stays open and is marked stale

### Requirement: Paper path isolation

The paper execution path SHALL never import or call the exchange layer
(`trading/exchanges/`), `ExchangeAdapter` or `ExecutionEngine`, and SHALL be
enforced by a static import test.

#### Scenario: The exchange layer is unreachable from the paper path

- WHEN the paper path modules are parsed
- THEN none imports the exchange layer or the execution engine

