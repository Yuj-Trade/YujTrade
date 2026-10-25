import json
from unittest.mock import AsyncMock

import pytest

from common.core import FundamentalAnalysis
from data.sources.coingecko_fetcher import CoinGeckoFetcher


def _fetcher(redis_client=None, api_key=None, tier="demo"):
    fetcher = CoinGeckoFetcher(api_key=api_key, redis_client=redis_client)
    fetcher.api_tier = tier
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 3600
    return fetcher


COIN_LIST = [
    {"id": "bitcoin", "symbol": "btc"},
    {"id": "ethereum", "symbol": "eth"},
]


class TestCoinIdResolution:
    async def test_coin_id_comes_from_the_coin_list(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_coins_list", AsyncMock(return_value=COIN_LIST))

        assert await fetcher._get_coin_id("BTC/USDT") == "bitcoin"

    async def test_unknown_symbol_falls_back_to_the_lowercase_ticker(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_coins_list", AsyncMock(return_value=COIN_LIST))

        assert await fetcher._get_coin_id("XYZ/USDT") == "xyz"

    async def test_coin_list_failure_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_coins_list", AsyncMock(return_value=[]))

        assert await fetcher._get_coin_id("BTC/USDT") is None

    async def test_coin_list_is_fetched_once(self, monkeypatch):
        fetcher = _fetcher()
        request = AsyncMock(return_value=COIN_LIST)
        monkeypatch.setattr(fetcher, "get_coins_list", request)

        await fetcher._get_coin_id("BTC/USDT")
        await fetcher._get_coin_id("ETH/USDT")

        assert request.await_count == 1


class TestCoinsListAndTrending:
    async def test_coins_list_is_cached(self, monkeypatch):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)
        monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=COIN_LIST))

        result = await fetcher.get_coins_list()

        assert result == COIN_LIST
        redis.set.assert_awaited_once()

    async def test_coins_list_cache_hit(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(COIN_LIST))
        fetcher = _fetcher(redis_client=redis)
        fetcher._fetch_json = AsyncMock()

        assert await fetcher.get_coins_list() == COIN_LIST
        fetcher._fetch_json.assert_not_awaited()

    async def test_coins_list_empty_payload_returns_empty_list(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=None))

        assert await fetcher.get_coins_list() == []

    async def test_trending_searches_extract_symbols(self, monkeypatch):
        fetcher = _fetcher()
        payload = {"coins": [{"item": {"symbol": "btc"}}, {"item": {"symbol": "eth"}}]}
        monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=payload))

        assert await fetcher.get_trending_searches() == ["btc", "eth"]

    async def test_trending_without_coins_returns_empty_list(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value={}))

        assert await fetcher.get_trending_searches() == []

    async def test_trending_is_cached(self, monkeypatch):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)
        monkeypatch.setattr(
            fetcher, "_fetch_json", AsyncMock(return_value={"coins": [{"item": {"symbol": "btc"}}]})
        )

        await fetcher.get_trending_searches()

        redis.set.assert_awaited_once()


class TestFundamentalData:
    async def test_fundamental_data_is_mapped(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_coins_list", AsyncMock(return_value=COIN_LIST))
        payload = {
            "market_data": {"market_cap": {"usd": 1e12}, "total_volume": {"usd": 5e10}},
            "community_data": {"twitter_followers": 1000},
            "developer_data": {"pull_requests_merged": 10, "stars": 20},
        }
        monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=payload))

        result = await fetcher.get_fundamental_data("BTC/USDT")

        assert isinstance(result, FundamentalAnalysis)
        assert result.market_cap == 1e12
        assert result.community_score == 1000
        assert result.developer_score == pytest.approx(16.0)

    async def test_unknown_coin_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_coins_list", AsyncMock(return_value=[]))

        assert await fetcher.get_fundamental_data("BTC/USDT") is None

    async def test_empty_payload_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_coins_list", AsyncMock(return_value=COIN_LIST))
        monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=None))

        assert await fetcher.get_fundamental_data("BTC/USDT") is None

    async def test_fundamental_cache_hit(self, monkeypatch):
        redis = AsyncMock()
        cached = {
            "market_cap": 1.0,
            "total_volume": 2.0,
            "developer_score": 3.0,
            "community_score": 4.0,
        }
        redis.get = AsyncMock(return_value=json.dumps(cached))
        fetcher = _fetcher(redis_client=redis)
        monkeypatch.setattr(fetcher, "get_coins_list", AsyncMock(return_value=COIN_LIST))
        fetcher._fetch_json = AsyncMock()

        result = await fetcher.get_fundamental_data("BTC/USDT")

        assert result.market_cap == 1.0
        fetcher._fetch_json.assert_not_awaited()
