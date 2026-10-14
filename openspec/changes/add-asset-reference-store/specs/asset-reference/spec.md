# Capability: asset-reference

## ADDED Requirements

### Requirement: Seeded provider identifiers

The system SHALL resolve CoinGecko ids and Messari slugs for base tickers
from a tracked seed file, falling back to the existing derivation logic
when a field is `null` or the base is unknown.

#### Scenario: Seeded Bitcoin id skips the coin list

- GIVEN the seed maps `BTC` to CoinGecko id `bitcoin`
- WHEN `CoinGeckoFetcher._get_coin_id("BTC/USDT")` is called
- THEN it returns `bitcoin` and `get_coins_list` is never awaited

#### Scenario: Null id keeps the existing fallback

- GIVEN the seed maps a base to a `null` CoinGecko id
- WHEN `_get_coin_id` is called for that base
- THEN the existing coin-list lookup and lowercase fallback run unchanged

#### Scenario: Seeded LINK slug reaches the request path

- GIVEN the seed maps `LINK` to Messari slug `chainlink`
- WHEN `MessariFetcher.get_asset_metrics("LINK/USDT")` is called
- THEN the request path uses `chainlink`

#### Scenario: Null slug keeps the derived slug

- GIVEN the seed maps a base to a `null` Messari slug
- WHEN `get_asset_metrics` is called for that base
- THEN the request path uses the lowercased base symbol as today

### Requirement: SQLite profile persistence

The system SHALL persist successfully fetched CoinGecko profiles
(genesis date, categories, max supply) in SQLite with a 7-day TTL and
serve them without changing the dynamic fetch path.

#### Scenario: Successful response writes a profile

- GIVEN a successful `/coins/{id}` response for input `BTC/USDT`
- WHEN the response is processed
- THEN a profile row for base `BTC` is stored and the dynamic
  `FundamentalAnalysis` is still returned from the live response

#### Scenario: Bare identifiers never write

- GIVEN fetcher input without `/` (for example `bitcoin`)
- WHEN the response is processed
- THEN no profile row is written

#### Scenario: Exact-boundary expiry

- GIVEN a stored row with `fetched_at + ttl` equal to now
- WHEN `get_profile` is called
- THEN it returns `None`

#### Scenario: Corrupt database degrades gracefully

- GIVEN `runs/asset_reference.db` is missing or corrupted
- WHEN analysis runs
- THEN the run completes, an error is logged, identifiers still resolve,
  and signals are still produced

### Requirement: Fetcher constructor compatibility

Every fetcher SHALL accept the `asset_reference` keyword without raising,
so the shared wiring dict keeps working.

#### Scenario: All fetchers construct with the store

- GIVEN an `AssetReferenceStore` instance
- WHEN each fetcher class is constructed with
  `asset_reference=<store>` through the provider wiring
- THEN no constructor raises `TypeError`

### Requirement: Seed coverage

The seed SHALL contain exactly one entry per base ticker in `symbols.txt`
with uppercase keys.

#### Scenario: Universe coverage

- GIVEN the tickers in `symbols.txt`
- WHEN the seed file is loaded
- THEN every base ticker has an entry and every key is uppercase
