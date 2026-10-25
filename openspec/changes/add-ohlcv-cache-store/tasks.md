# Tasks: add-ohlcv-cache-store

## 1. Configuration

- [ ] 1.1 Add `ohlcv_store_path` (`runs/ohlcv.db`), `ohlcv_store_enabled`
  and `ohlcv_store_max_rows_per_series` to `ConfigManager.DEFAULT_CONFIG`
- [ ] 1.2 Document the layout in `docs/architecture.md`

## 2. Store

- [ ] 2.1 Add `data/ohlcv_store.py` with `OhlcvStore`: WAL, busy timeout,
  schema `candles(symbol, timeframe, ts, open, high, low, close, volume,
  PRIMARY KEY(symbol, timeframe, ts))` and an index on `(symbol, timeframe, ts DESC)`
- [ ] 2.2 Implement `write_many` (upsert), `read(symbol, timeframe, limit)`
  returning a UTC-indexed DataFrame, `coverage(symbol, timeframe)` and
  `close()`
- [ ] 2.3 Keep every method non-throwing for callers: errors are logged once
  and surface as `None`/`False`

## 3. Wiring

- [ ] 3.1 Construct and close the store in `MarketDataProvider`
  `initialize()`/`close()`
- [ ] 3.2 `fetch_ohlcv_data`: Redis → store → network, backfilling both tiers
- [ ] 3.3 Drop `limit` from the OHLCV cache key and keep the store key
  canonical; update `CacheKeyBuilder`
- [ ] 3.4 Add `prewarm(symbols, timeframes, limit)` and wire it to the
  composition root behind a config flag

## 4. Verification

- [ ] 4.1 Unit tests: merge/idempotence, tiered read with Redis absent,
  backfill, degraded store, prewarm coverage
- [ ] 4.2 Run the default gate plus `ruff check`, `ruff format --check`,
  `mypy domain`; confirm golden hashes unchanged
