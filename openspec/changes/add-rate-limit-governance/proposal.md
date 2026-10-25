# Proposal: add-rate-limit-governance

## Why

Every fetcher declares its own module-level `RateLimiter` with hardcoded
numbers (`binance_fetcher.py:23` 1200/60, `coingecko_fetcher.py:19` 8/60,
`alphavantage_fetcher.py:10` 5/60, and five more). Three consequences:

- The numbers are code, not configuration, so they cannot be tuned without a
  commit and cannot differ per environment.
- Limiters are per module, not per provider. `MarketIndicesFetcher` calls
  `CoinGeckoFetcher._fetch_json` **without** a limiter for `/global` and the
  index paths, so those requests bypass the 8/minute budget entirely while
  still counting against the provider's real quota.
- A 429 is retried by `async_retry` with a fixed 5 s backoff and ignores the
  `Retry-After` header, so the bot retries into the same wall and the shared
  limiter keeps issuing requests during the penalty.

The 2026-10-24 run shows the cost: seven `Rate limit hit for cpi. Sleeping for
36.76s` events and a CoinDesk 429 retry, all with no visibility into which
source was throttled or how often.

## What Changes

- A single `RateLimitRegistry` in `common/rate_limit.py` owns one limiter per
  provider, created lazily from configuration and shared by every fetcher that
  talks to that provider.
- Per-provider limits move to `rate_limits` in `indicator_weights.json`
  (tracked) with defaults in `ConfigManager.DEFAULT_CONFIG`.
- `RateLimiter` gains a cooldown: a 429 with `Retry-After` parks the provider
  until the deadline instead of sleeping one caller at a time.
- `BaseFetcher` resolves its limiter from the registry by `source_name`;
  module-level limiter globals are removed.
- `MarketIndicesFetcher` passes the registry limiter on every CoinGecko call.
- `snapshot()` exposes per-provider request and throttle counters for
  observability.

Not a breaking change: the public fetcher signatures and the
`fetch_ohlcv_data` contract are unchanged.

## Impact

- Affected specs: `rate-limit-governance` (new)
- Affected code: `common/rate_limit.py` (new), `common/utils.py`,
  `data/sources/base_fetcher.py`, the eight fetcher modules,
  `data/sources/marketindices_fetcher.py`, `config/settings.py`,
  `indicator_weights.json`
- Tests: new `tests/unit/common/test_rate_limit_registry.py`; existing
  `tests/unit/common/test_rate_limiter.py` and fetcher tests stay green.
