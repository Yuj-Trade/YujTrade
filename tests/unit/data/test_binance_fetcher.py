from unittest.mock import AsyncMock

import pytest

from common.core import OrderBook
from common.exceptions import DataError, InvalidSymbolError
from data.sources.binance_fetcher import BinanceFetcher

KLINE = [
    [
        1704067200000,
        "42000.0",
        "42500.0",
        "41800.0",
        "42300.0",
        "120.5",
        1704070799999,
        "5100000",
        900,
        "60",
        "2540000",
        "0",
    ]
]


def _fetcher(redis_client=None):
    fetcher = BinanceFetcher(redis_client=redis_client)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 300
    return fetcher


class TestHistoricalOhlc:
    async def test_klines_are_parsed_into_a_numeric_frame(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=KLINE))

        frame = await fetcher.get_historical_ohlc("BTC/USDT", "1h", 1)

        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.tz is not None
        assert frame["close"].iloc[-1] == pytest.approx(42300.0)

    async def test_empty_response_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=[]))

        assert await fetcher.get_historical_ohlc("BTC/USDT", "1h", 1) is None

    async def test_invalid_symbol_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=InvalidSymbolError("bad")))

        assert await fetcher.get_historical_ohlc("NOPE/USDT", "1h", 1) is None

    async def test_other_failures_raise_data_error(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("boom")))

        with pytest.raises(DataError):
            await fetcher.get_historical_ohlc("BTC/USDT", "1h", 1)

    async def test_rows_with_unparsable_numbers_are_dropped(self, monkeypatch):
        broken = [list(KLINE[0])]
        broken[0][4] = "not-a-number"
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=broken))

        frame = await fetcher.get_historical_ohlc("BTC/USDT", "1h", 1)

        assert frame.empty


class TestDerivativeGetters:
    @pytest.mark.parametrize("symbol", ["ASTR/USDT", "SHIB/USDT", "PEPE/USDT"])
    async def test_blacklisted_symbols_are_skipped(self, symbol):
        fetcher = _fetcher()
        fetcher._fetch = AsyncMock()

        assert await fetcher.get_open_interest(symbol) is None
        assert await fetcher.get_mark_price(symbol) is None
        assert await fetcher.get_funding_rate(symbol) is None
        fetcher._fetch.assert_not_awaited()

    async def test_open_interest_is_returned_and_cached(self, monkeypatch):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={"openInterest": "1234.5"}))

        assert await fetcher.get_open_interest("BTC/USDT") == pytest.approx(1234.5)
        redis.set.assert_awaited_once()

    async def test_open_interest_cache_hit(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value="999")
        fetcher = _fetcher(redis_client=redis)
        fetcher._fetch = AsyncMock()

        assert await fetcher.get_open_interest("BTC/USDT") == pytest.approx(999.0)
        fetcher._fetch.assert_not_awaited()

    async def test_open_interest_without_the_field_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={}))

        assert await fetcher.get_open_interest("BTC/USDT") is None

    async def test_open_interest_failure_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_open_interest("BTC/USDT") is None

    async def test_mark_price(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={"markPrice": "42.5"}))

        assert await fetcher.get_mark_price("BTC/USDT") == pytest.approx(42.5)

    async def test_funding_rate_primary_endpoint(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=[{"fundingRate": "0.0001"}]))

        assert await fetcher.get_funding_rate("BTC/USDT") == pytest.approx(0.0001)

    async def test_funding_rate_falls_back_to_premium_index(self, monkeypatch):
        calls = []

        async def _fetch(url, endpoint, params=None):
            calls.append(endpoint)
            if endpoint == "fundingRate":
                raise RuntimeError("primary down")
            return {"lastFundingRate": "0.0002"}

        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", _fetch)

        assert await fetcher.get_funding_rate("BTC/USDT") == pytest.approx(0.0002)
        assert calls == ["fundingRate", "premiumIndex"]

    async def test_funding_rate_returns_none_when_both_paths_fail(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_funding_rate("BTC/USDT") is None

    async def test_taker_ratio(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=[{"buySellRatio": "1.35"}]))

        assert await fetcher.get_taker_long_short_ratio("BTC/USDT") == pytest.approx(1.35)

    async def test_top_trader_account_ratio(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=[{"longShortRatio": "2.0"}]))

        assert await fetcher.get_top_trader_long_short_ratio_accounts("BTC/USDT") == pytest.approx(
            2.0
        )

    async def test_ratio_failure_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_taker_long_short_ratio("BTC/USDT") is None


class TestOrderBookAndTicker:
    async def test_depth_is_converted_to_an_order_book(self, monkeypatch):
        payload = {"bids": [["100.0", "2.0"], ["99.5", "1.0"]], "asks": [["100.5", "3.0"]]}
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=payload))

        book = await fetcher.get_order_book_depth("BTC/USDT")

        assert isinstance(book, OrderBook)
        assert book.bid_ask_spread == pytest.approx(0.5)
        assert book.total_bid_volume == pytest.approx(3.0)
        assert book.total_ask_volume == pytest.approx(3.0)

    async def test_empty_depth_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=None))

        assert await fetcher.get_order_book_depth("BTC/USDT") is None

    async def test_depth_without_levels_has_zero_spread(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={"bids": [], "asks": []}))

        book = await fetcher.get_order_book_depth("BTC/USDT")

        assert book.bid_ask_spread == 0

    async def test_depth_failure_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_order_book_depth("BTC/USDT") is None

    async def test_ticker_is_mapped(self, monkeypatch):
        payload = {"lastPrice": "101.5", "volume": "1000", "priceChange": "-2"}
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=payload))

        ticker = await fetcher.get_24h_ticker("BTC/USDT")

        assert ticker["last_price"] == pytest.approx(101.5)
        assert ticker["volume"] == pytest.approx(1000.0)
        assert ticker["price_change"] == pytest.approx(-2.0)

    async def test_ticker_price(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={"price": "77.7"}))

        assert await fetcher.get_ticker_price("BTC/USDT") == pytest.approx(77.7)

    async def test_kline_data_returns_the_raw_rows(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=KLINE))

        rows = await fetcher.get_kline_data("BTC/USDT", "1h", limit=1)

        assert rows == KLINE

    async def test_kline_data_failure_returns_empty_list(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_kline_data("BTC/USDT", "1h") == []

    async def test_liquidation_orders_are_deprecated(self):
        fetcher = _fetcher()

        assert await fetcher.get_liquidation_orders("BTC/USDT") == []
