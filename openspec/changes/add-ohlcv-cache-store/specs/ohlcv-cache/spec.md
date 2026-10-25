## ADDED Requirements

### Requirement: Canonical Candle Series

The system SHALL store at most one candle row per symbol, timeframe and
timestamp, independent of how many rows a caller requested.

#### Scenario: Overlapping fetches merge
- **WHEN** a 500-row fetch is stored and a later 1000-row fetch overlaps it
- **THEN** the store holds 1000 distinct rows for that symbol/timeframe and no
  timestamp appears twice

#### Scenario: Repeated identical fetch is idempotent
- **WHEN** the same window is stored twice
- **THEN** the row count and every stored value are unchanged

### Requirement: Tiered Candle Read

The system SHALL serve candles from the hottest available tier: Redis, then the
durable store, then the network.

#### Scenario: Store answers when Redis is unavailable
- **WHEN** Redis is not connected and the store holds the requested series
- **THEN** `fetch_ohlcv_data` returns the stored candles without a network call

#### Scenario: Network result backfills both tiers
- **WHEN** a network fetch succeeds
- **THEN** the candles are written to the store and to Redis

### Requirement: Store Failure Degrades Gracefully

The system SHALL never fail a data request because the candle store failed.

#### Scenario: Store raises on read
- **WHEN** the store cannot be read
- **THEN** the request continues to the network path and the failure is logged
  once, not per symbol

### Requirement: Configured Coverage Prewarm

The system SHALL be able to prewarm the store for the configured symbol and
timeframe matrix.

#### Scenario: Prewarm fills every configured pair
- **WHEN** prewarm runs with `SYMBOLS` and `TIME_FRAMES`
- **THEN** it requests one series per pair and reports the pairs it could not
  fill without raising
