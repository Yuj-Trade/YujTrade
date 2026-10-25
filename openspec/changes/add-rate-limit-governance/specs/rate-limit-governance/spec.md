## ADDED Requirements

### Requirement: Per-Provider Rate Limit Configuration

The system SHALL resolve rate limits per provider from configuration, not from
literals in fetcher modules.

#### Scenario: Configured limit is applied
- **WHEN** `rate_limits.coingecko` declares `max_requests: 6` and `time_window: 60`
- **THEN** every CoinGecko request waits on a limiter created with those values

#### Scenario: Missing provider falls back to the default
- **WHEN** a provider has no entry in `rate_limits`
- **THEN** the registry creates its limiter from `rate_limits.default`

### Requirement: Shared Limiter Per Provider

The system SHALL share one limiter instance per provider across all fetchers
that call that provider.

#### Scenario: Index fetcher consumes the CoinGecko budget
- **WHEN** `MarketIndicesFetcher` requests a CoinGecko endpoint
- **THEN** the request waits on the same limiter as `CoinGeckoFetcher`

#### Scenario: Sibling endpoints do not block each other
- **WHEN** one endpoint of a provider is saturated
- **THEN** another endpoint of the same provider still proceeds once its own
  window allows it

### Requirement: Retry-After Honouring Cooldown

The system SHALL park a provider for the duration announced by a 429
`Retry-After` header instead of retrying immediately.

#### Scenario: Retry-After is respected
- **WHEN** a provider answers 429 with `Retry-After: 30`
- **THEN** no request to that provider is issued for 30 seconds and the
  cooldown is reported once at WARNING

#### Scenario: Cooldown expires
- **WHEN** the cooldown deadline has passed
- **THEN** the next request is allowed through and the cooldown is cleared

### Requirement: Rate Limit Observability

The system SHALL expose per-provider request and throttle counters.

#### Scenario: Snapshot reports counters
- **WHEN** the registry snapshot is requested
- **THEN** it returns, per provider, the configured limits, the requests
  issued in the current window and the number of throttle events
