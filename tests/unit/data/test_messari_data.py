import json
from unittest.mock import AsyncMock

from common.core import OnChainAnalysis
from data.sources.messari_fetcher import MessariFetcher


class _Config:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def get(self, key, default=None):
        if key == "messari_enabled":
            return self.enabled
        return default


def _fetcher(enabled=True, redis_client=None):
    fetcher = MessariFetcher(api_key="test-key", config_manager=_Config(enabled))
    fetcher.redis = redis_client
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 3600
    return fetcher


METRICS = {
    "market_data": {"mvrv_usd": 2.5},
    "on_chain_data": {"sopr": 1.02, "active_addresses": 900000},
    "marketcap": {"realized_marketcap_usd": 5e11},
}


class TestGating:
    async def test_disabled_metrics_make_no_request(self):
        fetcher = _fetcher(enabled=False)
        fetcher._fetch = AsyncMock()

        assert await fetcher.get_asset_metrics("BTC/USDT") is None
        fetcher._fetch.assert_not_awaited()

    async def test_disabled_news_returns_empty_list(self):
        fetcher = _fetcher(enabled=False)
        fetcher._fetch = AsyncMock()

        assert await fetcher.get_news("BTC/USDT") == []
        fetcher._fetch.assert_not_awaited()


class TestAssetMetrics:
    async def test_metrics_are_returned_and_cached(self, monkeypatch):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={"data": METRICS}))

        result = await fetcher.get_asset_metrics("BTC/USDT")

        assert result == METRICS
        redis.set.assert_awaited_once()

    async def test_payload_without_data_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={}))

        assert await fetcher.get_asset_metrics("BTC/USDT") is None

    async def test_failure_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_asset_metrics("BTC/USDT") is None

    async def test_cache_hit_skips_the_request(self, monkeypatch):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps(METRICS))
        fetcher = _fetcher(redis_client=redis)
        fetcher._fetch = AsyncMock()

        assert await fetcher.get_asset_metrics("BTC/USDT") == METRICS
        fetcher._fetch.assert_not_awaited()


class TestOnChainData:
    async def test_metrics_are_mapped_to_the_dataclass(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_asset_metrics", AsyncMock(return_value=METRICS))

        result = await fetcher.get_on_chain_data("BTC/USDT")

        assert isinstance(result, OnChainAnalysis)
        assert result.mvrv == 2.5
        assert result.sopr == 1.02
        assert result.active_addresses == 900000

    async def test_missing_metrics_return_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "get_asset_metrics", AsyncMock(return_value=None))

        assert await fetcher.get_on_chain_data("BTC/USDT") is None

    async def test_cache_hit_returns_the_dataclass(self, monkeypatch):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"mvrv": 1.0, "sopr": 1.0}))
        fetcher = _fetcher(redis_client=redis)
        monkeypatch.setattr(fetcher, "get_asset_metrics", AsyncMock())

        result = await fetcher.get_on_chain_data("BTC/USDT")

        assert result.mvrv == 1.0
        fetcher.get_asset_metrics.assert_not_awaited()

    async def test_mapping_failure_returns_none(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(
            fetcher, "get_asset_metrics", AsyncMock(return_value={"market_data": "bad"})
        )

        assert await fetcher.get_on_chain_data("BTC/USDT") is None


class TestNews:
    async def test_news_are_returned(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={"data": [{"title": "a"}]}))

        assert await fetcher.get_news("BTC/USDT") == [{"title": "a"}]

    async def test_payload_without_data_returns_empty_list(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={}))

        assert await fetcher.get_news("BTC/USDT") == []

    async def test_failure_returns_empty_list(self, monkeypatch):
        fetcher = _fetcher()
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(side_effect=RuntimeError("down")))

        assert await fetcher.get_news("BTC/USDT") == []

    async def test_news_are_cached(self, monkeypatch):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)
        monkeypatch.setattr(fetcher, "_fetch", AsyncMock(return_value={"data": [{"title": "a"}]}))

        await fetcher.get_news("BTC/USDT")

        redis.set.assert_awaited_once()
