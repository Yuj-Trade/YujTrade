# market-data Specification

## Purpose
TBD - created by archiving change add-time-range-ohlcv-fetch. Update Purpose after archive.
## Requirements
### Requirement: Time-range OHLCV fetch

`MarketDataProvider` SHALL provide `fetch_ohlcv_range(symbol, timeframe,
start, end)` that returns the candles whose open time lies in the
`[start, end]` window. Both bounds SHALL be timezone-aware UTC and
`start` SHALL precede `end`. The method SHALL read and write neither Redis
nor the OHLCV store, and SHALL page through the range-capable source with a
bounded page size.

#### Scenario: A window is paged and assembled

- GIVEN a range-capable fake source that returns three pages
- WHEN the range is fetched
- THEN every page is requested and the union of the pages is returned in
  time order

#### Scenario: A short page ends the pagination

- GIVEN a page shorter than the page size
- WHEN the range is fetched
- THEN no further page is requested

#### Scenario: The window is empty

- GIVEN a window in which the source holds no candle
- WHEN the range is fetched
- THEN an empty frame is returned and no error is raised

#### Scenario: An invalid window is rejected

- WHEN `start` is not before `end`, or a bound is naive
- THEN `ValueError` is raised

#### Scenario: No range-capable source exists

- WHEN no source can serve a range
- THEN `InsufficientDataError` is raised

#### Scenario: The provider is closed

- WHEN the provider has been closed
- THEN `ObjectClosedError` is raised

### Requirement: Range-based outcome resolution

The outcome watch and the signal resolution SHALL fetch the candles by time
range instead of by count. When the window holds no candle and the current
instant is before the window end, the signal SHALL stay pending. When the
window holds no candle and the current instant is at or after the window
end, the signal SHALL resolve to `no_data` through the domain resolver.

#### Scenario: An open window without candles stays pending

- GIVEN no candles and the current instant inside the expiry window
- WHEN the signal is resolved
- THEN the result is `None` and the signal stays pending

#### Scenario: A closed window without candles is no data

- GIVEN no candles and the current instant after the expiry window
- WHEN the signal is resolved
- THEN the exit reason is `no_data`

#### Scenario: The watch fetches by range

- GIVEN an open signal
- WHEN the watch observes it
- THEN the provider is called with a range, not with a count

### Requirement: One kline parser

The Binance fetcher SHALL build its OHLCV frame through one module-level
function, so the count path and the range path keep the same columns, the
same UTC index and the same numeric coercion.

#### Scenario: Both paths share the parser

- GIVEN a raw klines payload
- WHEN the frame is built by the count path and by the range path
- THEN both frames are equal

