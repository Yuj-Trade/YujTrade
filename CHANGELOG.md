# Changelog

All notable changes to this project are documented here.
This project follows Semantic Versioning.

## [6.0.4] - 2026-11-04

Patch release. Makes the operator scripts runnable again from the command line.

### Fixed

- `python scripts/train_models.py` (and every other project script invoked
  directly) failed with `ModuleNotFoundError: No module named 'common'`:
  running a file inside `scripts/` puts `scripts/` first on `sys.path`, so the
  repository root was never importable. Five scripts
  (`train_models`, `encrypt_keys`, `exchange_shadow_report`,
  `probe_exchanges`, `seed_exchange_env_names`) now insert the repository root
  into `sys.path` before importing project code, matching the pattern already
  used by the other scripts. A regression test runs every eligible script in a
  subprocess and fails on any import error.

## [6.0.3] - 2026-11-04

Patch release. Hardens Telegram startup against transient network failures and
stops the bot token from leaking into logs.

### Fixed

- Telegram startup crashed with a full traceback when `api.telegram.org` was
  unreachable (`httpx.ConnectTimeout` during `application.initialize()`).
  Startup now retries `initialize`/`start`/`start_polling` up to four times with
  exponential backoff, honours `RetryAfter`, and on final failure raises a clean
  `RuntimeError` logged without a traceback.
- The bot token was printed in traceback frames (the `https://api.telegram.org/
  bot<id>:<token>` URL). The logger patcher now redacts the `bot<id>:<token>`
  pattern from messages and exception values before any sink renders them.

## [6.0.2] - 2026-11-04

Patch release from a full run and analysis. Fixes a Telegram error-handling
gap and makes the weekly/monthly analysis pass against real venue history.

### Fixed

- No Telegram error handler was registered, so a transient transport failure
  (for example `httpx.ConnectTimeout` on `start`) logged the full "No error
  handlers are registered" traceback. The bot now registers `handle_error`,
  which absorbs `TimedOut`, `NetworkError`, `RetryAfter`, `Forbidden` and
  `BadRequest` as warnings and only logs an unexpected error at error level.
  `_reply` and the `/start` reply also swallow `TimedOut`/`NetworkError` so a
  slow network no longer surfaces as an exception.
- `min_data_points` for `1w` (200) and `1M` (150) exceeded the history real
  venues expose; for example Binance returns 112 monthly candles for BTC and
  43 for SUI, so `validate_data_quality` rejected every weekly/monthly
  analysis with `Insufficient data`. Lowered to `1w` 150 and `1M` 40, which
  still leaves enough candles for the long-term indicators and lets every
  symbol in the list analyze. The backtesting window tests now derive the
  expected window count from the constant instead of a hardcoded 150.

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
