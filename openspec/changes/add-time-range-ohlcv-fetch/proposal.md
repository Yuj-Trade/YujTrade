# Proposal: add-time-range-ohlcv-fetch

Approval: approved by YT-IMPL-SPEC Revision 2.0 (2026-10-29), decision G1.

## Why

`MarketDataProvider.fetch_ohlcv_data` only accepts a candle count. The
outcome watch (`_watch_group`) and the resolution path
(`_resolve_signal_outcome`) derive a count from the expiry and then fail the
coverage check when the window is not fully covered, which produces
`no_data` outcomes and missed notifications (open issues 10 and 17).
Binance already exposes `get_kline_data(symbol, interval, start_time,
end_time, limit)`, which the provider does not use.

## What Changes

- `MarketDataProvider.fetch_ohlcv_range(symbol, timeframe, start, end)`
  pages through `get_kline_data` with 1000 candles per page and returns the
  candles that exist in the window.
- `_watch_group` fetches by range from the oldest open signal to now.
- `_resolve_signal_outcome` fetches by range over the expiry window and
  takes a required `now` argument.
- The DataFrame construction in `BinanceFetcher.get_historical_ohlc` moves
  into a module-level `klines_to_frame` so both callers share one parser.
- **BREAKING** for the internal service signature: `_resolve_signal_outcome`
  gains `now` and loses the count.

## Impact

- Affected specs: `market-data`
- Affected code: `data/data_provider.py`,
  `data/sources/binance_fetcher.py`, `services/trading_service.py`,
  `tests/unit/services/test_outcome_watch.py`,
  `tests/unit/services/test_reconciliation_resolution.py`,
  `tests/unit/services/test_service_delegation.py`
- Closes open issues 10 and 17.
