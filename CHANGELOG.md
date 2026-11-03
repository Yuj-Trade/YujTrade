# Changelog

All notable changes to this project are documented here.
This project follows Semantic Versioning.

## [6.0.1] - 2026-11-04

Patch release from a full run analysis. Fixes two data-layer defects that made
weekly and monthly analysis fail and blocked range fetches during startup.

### Fixed

- OHLCV gap detection rejected every weekly and monthly series. The repair
  check built its expected grid with a calendar rule anchored on the wrong day
  (`1W` aligns to Sunday, `1M` used a fixed `30D`), so real Monday-based weekly
  candles and variable-length months were counted as gaps and the whole series
  was discarded. The check now compares against calendar-aligned grids
  (`W-MON`/`W-SUN`, `MS`/`ME`) and picks the best fit. This removes the
  `OHLCV gap exceeds repair tolerance` and `Failed to fetch sufficient OHLCV
  ... on 1w/1M` errors seen at run time.
- Range fetch could fail with `No range-capable source` when it started before
  the provider finished constructing its fetcher (the session was open but the
  fetcher was still `None`). Both `fetch_ohlcv_data` and `fetch_ohlcv_range`
  now reinitialize when the fetcher is missing.

### Changed

- Removed unused dependency declarations (`web3`, its `eth-*` family,
  `pydantic`, `SQLAlchemy`, `alembic`); `SQLAlchemy` remains only as a
  transitive dependency of `optuna`.
- The container builds from `requirements.txt` and asserts `import ccxt` at
  build time, replacing the stale `requirements.lock`.
- Pinned GitHub Actions to commit SHAs with read-only token permissions.

## [6.0.0]

Initial tracked release baseline.
