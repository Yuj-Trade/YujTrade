from unittest.mock import AsyncMock

import pandas as pd
import pytest

from data.sources.coindesk_fetcher import CoinDeskFetcher

OHLC_PAYLOAD = {
    "Data": [
        {
            "TIMESTAMP": 1704067200,
            "OPEN": 42000.0,
            "HIGH": 42500.0,
            "LOW": 41800.0,
            "CLOSE": 42300.0,
            "VOLUME": 120.5,
        },
        {
            "TIMESTAMP": 1704070800,
            "OPEN": 42300.0,
            "HIGH": 42600.0,
            "LOW": 42100.0,
            "CLOSE": 42400.0,
            "VOLUME": 110.0,
        },
    ]
}


def _fetcher(redis_client=None, api_key="test-key"):
    fetcher = CoinDeskFetcher(api_key=api_key, redis_client=redis_client)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 300
    return fetcher


class TestSupportsOhlcv:
    @pytest.mark.parametrize("symbol", ["BTC/USDT", "ETH/USDT", "btc/usdt"])
    def test_supported_bases(self, symbol):
        assert _fetcher().supports_ohlcv(symbol) is True

    @pytest.mark.parametrize("symbol", ["SOL/USDT", "XRP/USDT", "BTC/USD"])
    def test_unsupported_bases(self, symbol):
        assert _fetcher().supports_ohlcv(symbol) is False


class TestHistoricalOhlc:
    async def test_payload_is_normalised(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=OHLC_PAYLOAD))

        frame = await fetcher.get_historical_ohlc("BTC/USDT", "1h", 2)

        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.tz is not None
        assert frame.index.is_monotonic_increasing
        assert frame["close"].iloc[-1] == pytest.approx(42400.0)

    async def test_daily_timeframe_uses_the_days_endpoint(self, monkeypatch):
        fetcher = _fetcher()
        seen = {}

        async def _fetch(endpoint, params=None):
            seen["endpoint"] = endpoint
            return OHLC_PAYLOAD

        monkeypatch.setattr(fetcher, "_fetch", _fetch)

        await fetcher.get_historical_ohlc("BTC/USDT", "1d", 2)

        assert seen["endpoint"] == "spot/v1/historical/days"

    async def test_hourly_timeframe_uses_the_hours_endpoint(self, monkeypatch):
        fetcher = _fetcher()
        seen = {}

        async def _fetch(endpoint, params=None):
            seen["endpoint"] = endpoint
            return OHLC_PAYLOAD

        monkeypatch.setattr(fetcher, "_fetch", _fetch)

        await fetcher.get_historical_ohlc("BTC/USDT", "1h", 2)

        assert seen["endpoint"] == "spot/v1/historical/hours"

    async def test_unsupported_symbol_returns_none_without_a_request(self, monkeypatch):
        fetcher = _fetcher()
        request = AsyncMock()
        monkeypatch.setattr(fetcher, "_fetch", request)

        assert await fetcher.get_historical_ohlc("SOL/USDT", "1h", 10) is None
        request.assert_not_awaited()

    @pytest.mark.parametrize("payload", [None, {}, {"Data": []}])
    async def test_empty_payload_returns_none(self, monkeypatch, payload):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=payload))

        assert await fetcher.get_historical_ohlc("BTC/USDT", "1h", 10) is None

    async def test_failure_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_historical_ohlc("BTC/USDT", "1h", 10) is None

    async def test_result_is_limited_to_the_requested_rows(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value=OHLC_PAYLOAD))

        frame = await fetcher.get_historical_ohlc("BTC/USDT", "1h", 1)

        assert len(frame) == 1
        assert isinstance(frame, pd.DataFrame)


class TestNews:
    async def test_news_are_deduplicated_by_id(self, monkeypatch):
        fetcher = _fetcher()

        class _Response:
            status = 200

            async def json(self):
                return {"data": [{"id": 1}, {"id": 1}, {"id": 2}]}

        class _Session:
            def get(self, url, params=None, headers=None):
                class _Ctx:
                    async def __aenter__(self):
                        return _Response()

                    async def __aexit__(self, *args):
                        return False

                return _Ctx()

        monkeypatch.setattr(fetcher, "_get_session", AsyncMock(return_value=_Session()))

        news = await fetcher.get_news(["BTC/USDT"])

        assert len(news) == 2

    async def test_non_200_returns_empty_list(self, monkeypatch):
        fetcher = _fetcher()

        class _Response:
            status = 500

        class _Session:
            def get(self, url, params=None, headers=None):
                class _Ctx:
                    async def __aenter__(self):
                        return _Response()

                    async def __aexit__(self, *args):
                        return False

                return _Ctx()

        monkeypatch.setattr(fetcher, "_get_session", AsyncMock(return_value=_Session()))

        assert await fetcher.get_news(["BTC/USDT"]) == []

    async def test_session_failure_returns_empty_list(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(
            fetcher, "_get_session", AsyncMock(side_effect=RuntimeError("no session"))
        )

        assert await fetcher.get_news(["BTC/USDT"]) == []
