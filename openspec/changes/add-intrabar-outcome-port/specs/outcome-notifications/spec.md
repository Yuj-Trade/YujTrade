# Capability: outcome-notifications

## ADDED Requirements

### Requirement: Intrabar price port

The application layer SHALL define an `IntrabarPriceFeed` protocol with an
async `last_price(symbol)` that returns a price or `None`, and the data
layer SHALL provide a null implementation that returns `None`. The outcome
watch SHALL NOT be wired to the port, so the detection stays on closed
candles.

#### Scenario: The null feed conforms to the protocol

- WHEN the null feed is asked for a price
- THEN it returns `None` and satisfies the protocol

#### Scenario: The watch is unchanged

- GIVEN an open signal
- WHEN the watch observes it
- THEN the detection still uses closed candles only

### Requirement: The faster notification is deferred

The ADR SHALL record that the faster notification is deferred because no
intrabar stream exists, that the port is reserved, and that the current
delay equals the candle duration plus the watch interval.

#### Scenario: The deferral is documented

- WHEN ADR-0010 is read
- THEN it names the deferral, the reserved port and the current latency
