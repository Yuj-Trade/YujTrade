# Tasks: add-rate-limit-governance

## 1. Configuration

- [ ] 1.1 Add `rate_limits` defaults to `ConfigManager.DEFAULT_CONFIG`:
  `default` plus one entry per provider (`binance`, `coingecko`, `coindesk`,
  `alphavantage`, `cryptopanic`, `defillama`, `messari`, `alternativeme`)
- [ ] 1.2 Mirror the same block in `indicator_weights.json` so it is tunable
  without a code change, and add `get_rate_limits()` to `ConfigManager`

## 2. Registry

- [ ] 2.1 Add `common/rate_limit.py` with `RateLimitRegistry`: lazy limiter per
  provider, `wait(provider, endpoint)`, `snapshot()`
- [ ] 2.2 Extend `RateLimiter` with a cooldown (`penalize(seconds)`) that
  parks the provider until a monotonic deadline, and count throttles
- [ ] 2.3 Log a cooldown once at WARNING with provider and duration

## 3. Wiring

- [ ] 3.1 `BaseFetcher` resolves its limiter from the registry using
  `source_name`; `_fetch_json` defaults to that limiter
- [ ] 3.2 Remove the module-level limiter globals from the eight fetchers and
  pass the provider name instead
- [ ] 3.3 `MarketIndicesFetcher` passes the CoinGecko limiter on `/global` and
  the index paths
- [ ] 3.4 `BaseFetcher` and the Binance/CoinGecko fetchers call
  `penalize(retry_after)` when a 429 carries `Retry-After`

## 4. Verification

- [ ] 4.1 Unit tests for configuration resolution, shared limiter, cooldown
  expiry, sibling-endpoint independence and the snapshot counters
- [ ] 4.2 Run the default gate plus `ruff check`, `ruff format --check`,
  `mypy domain`; confirm golden hashes unchanged
