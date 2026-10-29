import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from common.exceptions import InsufficientDataError, ObjectClosedError
from data.data_provider import MarketDataProvider
from data.sources.binance_fetcher import klines_to_frame

_START = datetime(2024, 1, 1, tzinfo=UTC)


def _rows(first: datetime, count: int) -> list[list[object]]:
    return [
        [
            int((first + timedelta(hours=index)).timestamp() * 1000),
            "100",
            "101",
            "99",
            "100.5",
            "10",
            0,
            "0",
            0,
            "0",
            "0",
            "0",
        ]
        for index in range(count)
    ]


def _provider(*pages) -> tuple[MarketDataProvider, SimpleNamespace]:
    provider = MarketDataProvider.__new__(MarketDataProvider)
    provider._is_closed = False
    provider.session = MagicMock()
    provider.session.closed = False
    provider.redis = None
    provider.ohlcv_store = None
    provider.data_quality_checker = MagicMock()
    fetcher = SimpleNamespace(get_kline_data=AsyncMock(side_effect=list(pages)))
    provider.binance_fetcher = fetcher
    return provider, fetcher


def test_pagination_across_three_pages():
    pages = [
        _rows(_START, 1000),
        _rows(_START + timedelta(hours=1000), 1000),
        _rows(_START + timedelta(hours=2000), 10),
    ]
    provider, fetcher = _provider(*pages)
    end = _START + timedelta(hours=2010)

    frame = asyncio.run(provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, end))

    assert fetcher.get_kline_data.await_count == 3
    assert len(frame) == 2010
    assert frame.index[0] == _START
    assert frame.index[-1] == end - timedelta(hours=1)


def test_the_cursor_advances_past_the_last_open_time():
    first_page = _rows(_START, 1000)
    second_page = _rows(_START + timedelta(hours=1000), 5)
    provider, fetcher = _provider(first_page, second_page)
    end = _START + timedelta(hours=1005)

    asyncio.run(provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, end))

    second_call = fetcher.get_kline_data.await_args_list[1]
    expected_start = int((_START + timedelta(hours=999)).timestamp() * 1000) + 1
    assert second_call.kwargs["start_time"] == expected_start


def test_a_short_page_ends_the_pagination():
    page = _rows(_START, 10)
    provider, fetcher = _provider(page)
    end = _START + timedelta(hours=10)

    frame = asyncio.run(provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, end))

    assert fetcher.get_kline_data.await_count == 1
    assert len(frame) == 10


def test_an_empty_response_returns_an_empty_frame():
    provider, fetcher = _provider([])
    end = _START + timedelta(hours=3)

    frame = asyncio.run(provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, end))

    assert frame.empty
    assert fetcher.get_kline_data.await_count == 1


def test_start_at_or_after_end_raises():
    provider, _ = _provider([])
    with pytest.raises(ValueError):
        asyncio.run(provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, _START))
    with pytest.raises(ValueError):
        asyncio.run(
            provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, _START - timedelta(hours=1))
        )


def test_a_naive_bound_raises():
    provider, _ = _provider([])
    with pytest.raises(ValueError):
        asyncio.run(
            provider.fetch_ohlcv_range(
                "BTC/USDT", "1h", datetime(2024, 1, 1), _START + timedelta(hours=1)
            )
        )


def test_a_closed_provider_raises_object_closed():
    provider, _ = _provider([])
    provider._is_closed = True
    with pytest.raises(ObjectClosedError):
        asyncio.run(
            provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, _START + timedelta(hours=1))
        )


def test_no_range_capable_source_raises_insufficient_data():
    provider, _ = _provider([])
    provider.binance_fetcher = None
    with pytest.raises(InsufficientDataError):
        asyncio.run(
            provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, _START + timedelta(hours=1))
        )


def test_the_range_fetch_does_not_touch_redis_or_the_store():
    provider, _ = _provider(_rows(_START, 3))
    redis = SimpleNamespace(get=AsyncMock(), set=AsyncMock())
    store = SimpleNamespace(read=AsyncMock(), write_many=AsyncMock())
    provider.redis = redis
    provider.ohlcv_store = store

    asyncio.run(provider.fetch_ohlcv_range("BTC/USDT", "1h", _START, _START + timedelta(hours=3)))

    redis.get.assert_not_called()
    redis.set.assert_not_called()
    store.read.assert_not_called()
    store.write_many.assert_not_called()


def test_the_frame_is_windowed_to_the_requested_range():
    provider, _ = _provider(_rows(_START, 10))
    start = _START + timedelta(hours=2)
    end = _START + timedelta(hours=5)

    frame = asyncio.run(provider.fetch_ohlcv_range("BTC/USDT", "1h", start, end))

    assert frame.index[0] == start
    assert frame.index[-1] == end


def test_klines_to_frame_builds_the_same_columns_and_index():
    frame = klines_to_frame(_rows(_START, 2))
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame.index[0] == _START
    assert frame["close"].iloc[0] == pytest.approx(100.5)
