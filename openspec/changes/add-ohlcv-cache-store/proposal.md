# Proposal: add-ohlcv-cache-store

## Why

Candles are the most reused data in the system and the least durably cached.

- The only cache is Redis. When Redis is unreachable — the state recorded as
  open issue U2 and reproduced in the 2026-10-24 run — every symbol and every
  timeframe is refetched from the network on every cycle. The log shows ten
  `Analyzing <symbol> on 1h` lines and no cache hits at all.
- The cache key embeds the requested `limit`
  (`CacheKeyBuilder.ohlcv_key(source, symbol, timeframe, limit)`), so a 500-row
  request and a 1000-row request store the same candles twice. Open issue 5
  records this duplication and the extra `mtf_analysis` copy.
- Nothing records what has already been downloaded, so the model trainer, the
  outcome watch and the analysis cycle each pay for the same history.

The symbols and timeframes are fixed (`symbols.txt`, `TIME_FRAMES`), so the
working set is small, known in advance, and can be stored as one organised
series per symbol/timeframe instead of per-request blobs.

## What Changes

- A new `OhlcvStore` (`data/ohlcv_store.py`) backed by SQLite (aiosqlite, WAL,
  busy timeout) with one table keyed by `(symbol, timeframe, timestamp)`. Rows
  are upserted, so re-fetching overlapping windows is idempotent and the store
  holds exactly one canonical series per symbol/timeframe.
- `MarketDataProvider.fetch_ohlcv_data` becomes three-tiered: Redis hot entry →
  `OhlcvStore` durable series → network. A network result is merged back into
  both tiers.
- The OHLCV cache key drops `limit`, so one entry serves every caller. This
  closes open issue 5 for the analysis path.
- A prewarm helper fills the store for the configured symbol × timeframe
  matrix, so the first cycle after a cold start reads from disk.
- Store failures never propagate: a broken store degrades to the previous
  behaviour and logs once.

Not a breaking change: `fetch_ohlcv_data` keeps its signature and returns the
same DataFrame shape.

## Impact

- Affected specs: `ohlcv-cache` (new)
- Affected code: `data/ohlcv_store.py` (new), `data/data_provider.py`,
  `common/cache.py`, `services/trading_service.py` (store lifecycle),
  `config/settings.py`, `indicator_weights.json`
- Data at rest: `runs/ohlcv.db` (gitignored, runtime)
- Tests: new `tests/unit/data/test_ohlcv_store.py`; existing data-provider
  tests stay green
