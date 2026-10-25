import json
from unittest.mock import AsyncMock

from data.sources.cryptopanic_fetcher import CryptoPanicFetcher


def _fetcher(redis_client=None):
    fetcher = CryptoPanicFetcher(api_key="test-key", redis_client=redis_client)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 600
    return fetcher


async def test_posts_request_carries_the_token_and_currency_filter(monkeypatch):
    fetcher = _fetcher()
    seen = {}

    async def _fake(url, params=None, headers=None, limiter=None, endpoint_name="default"):
        seen.update({"url": url, "params": params, "endpoint": endpoint_name})
        return {"results": [{"title": "news"}]}

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    result = await fetcher.fetch_posts(["BTC", "ETH"], kind="news")

    assert result == [{"title": "news"}]
    assert seen["url"] == "https://cryptopanic.com/api/v1/posts/"
    assert seen["params"] == {
        "auth_token": "test-key",
        "public": "true",
        "currencies": "BTC,ETH",
        "kind": "news",
    }
    assert seen["endpoint"] == "posts"


async def test_posts_without_filters_only_sends_the_token(monkeypatch):
    fetcher = _fetcher()
    seen = {}

    async def _fake(url, params=None, **kwargs):
        seen["params"] = params
        return {"results": []}

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    assert await fetcher.fetch_posts() == []
    assert seen["params"] == {"auth_token": "test-key", "public": "true"}


async def test_posts_response_without_results_is_empty(monkeypatch):
    fetcher = _fetcher()
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value={}))

    assert await fetcher.fetch_posts() == []


async def test_media_is_cached_after_a_successful_fetch(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value={"results": [{"id": 1}]}))

    result = await fetcher.fetch_media()

    assert result == [{"id": 1}]
    redis.set.assert_awaited_once()
    assert json.loads(redis.set.await_args.args[1]) == [{"id": 1}]


async def test_media_cache_hit_skips_the_request(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps([{"id": 2}]))
    fetcher = _fetcher(redis_client=redis)
    request = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(fetcher, "_fetch_json", request)

    assert await fetcher.fetch_media() == [{"id": 2}]
    request.assert_not_awaited()


async def test_empty_media_is_not_cached(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value={"results": []}))

    assert await fetcher.fetch_media() == []
    redis.set.assert_not_awaited()
