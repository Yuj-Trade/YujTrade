import json
from unittest.mock import AsyncMock

from data.sources.alternativeme_fetcher import AlternativeMeFetcher


def _fetcher(redis_client=None):
    fetcher = AlternativeMeFetcher(redis_client=redis_client)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 3600
    return fetcher


async def test_fetch_returns_the_data_array(monkeypatch):
    fetcher = _fetcher()
    payload = {"data": [{"value": "55", "value_classification": "Neutral"}]}
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=payload))

    result = await fetcher.fetch_fear_greed(limit=1)

    assert result == payload["data"]


async def test_fetch_uses_the_configured_limit_in_the_url(monkeypatch):
    fetcher = _fetcher()
    seen = {}

    async def _fake(url, params=None, headers=None, limiter=None, endpoint_name="default"):
        seen["url"] = url
        seen["endpoint"] = endpoint_name
        return {"data": []}

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    await fetcher.fetch_fear_greed(limit=7)

    assert seen["url"] == "https://api.alternative.me/fng/?limit=7"
    assert seen["endpoint"] == "fng"


async def test_missing_data_key_returns_empty_list(monkeypatch):
    fetcher = _fetcher()
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value={}))

    assert await fetcher.fetch_fear_greed() == []


async def test_cache_hit_skips_the_request(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps([{"value": "10"}]))
    fetcher = _fetcher(redis_client=redis)
    request = AsyncMock(return_value={"data": [{"value": "99"}]})
    monkeypatch.setattr(fetcher, "_fetch_json", request)

    result = await fetcher.fetch_fear_greed()

    assert result == [{"value": "10"}]
    request.assert_not_awaited()


async def test_cache_miss_stores_the_result(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value={"data": [{"value": "42"}]}))

    await fetcher.fetch_fear_greed()

    redis.set.assert_awaited_once()
    key, value = redis.set.await_args.args
    assert "fear_greed" in key
    assert json.loads(value) == [{"value": "42"}]


async def test_empty_result_is_not_cached(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value={"data": []}))

    await fetcher.fetch_fear_greed()

    redis.set.assert_not_awaited()


def test_source_name_is_stable():
    assert _fetcher().source_name == "alternative.me"
