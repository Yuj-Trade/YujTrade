from contextlib import asynccontextmanager

from data.sources.defillama_fetcher import DeFiLlamaFetcher


class _RecordingSession:
    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []
        self.closed = False

    def get(self, url, params=None, headers=None, **kwargs):
        self.urls.append(url)
        payload = self.payload

        @asynccontextmanager
        async def _ctx():
            class _Response:
                status = 200

                async def json(self):
                    return payload

                async def text(self):
                    return ""

            yield _Response()

        return _ctx()


async def test_chain_tvl_uses_v2_chains_endpoint():
    payload = [{"name": "Ethereum", "tvl": 1.0}, {"name": "Solana", "tvl": 2.0}]
    session = _RecordingSession(payload)
    fetcher = DeFiLlamaFetcher(session=session)

    result = await fetcher.get_total_tvl_for_chains()

    assert session.urls[0].endswith("/v2/chains")
    assert result == payload


async def test_non_list_chain_payload_returns_empty_list(monkeypatch):
    fetcher = DeFiLlamaFetcher(session=_RecordingSession({"error": "not a list"}))

    assert await fetcher.get_total_tvl_for_chains() == []


async def test_protocol_chart_is_cached(monkeypatch):
    from unittest.mock import AsyncMock

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = DeFiLlamaFetcher(session=_RecordingSession({"tvl": [1, 2]}), redis_client=redis)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 3600

    result = await fetcher.get_protocol_chart("aave")

    assert result == {"tvl": [1, 2]}
    redis.set.assert_awaited_once()


async def test_protocol_chart_cache_hit_skips_the_request(monkeypatch):
    import json
    from unittest.mock import AsyncMock

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps({"tvl": [9]}))
    session = _RecordingSession({"tvl": [1]})
    fetcher = DeFiLlamaFetcher(session=session, redis_client=redis)

    result = await fetcher.get_protocol_chart("aave")

    assert result == {"tvl": [9]}
    assert session.urls == []


async def test_protocols_endpoint_returns_a_list():
    payload = [{"name": "Aave"}, {"name": "Curve"}]
    fetcher = DeFiLlamaFetcher(session=_RecordingSession(payload))

    assert await fetcher.get_defi_protocols() == payload


async def test_protocols_empty_payload_returns_empty_list():
    fetcher = DeFiLlamaFetcher(session=_RecordingSession({}))

    assert await fetcher.get_defi_protocols() == []


async def test_chain_tvl_uses_the_metrics_category():
    from unittest.mock import AsyncMock

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = DeFiLlamaFetcher(session=_RecordingSession({"tvl": 5}), redis_client=redis)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 3600

    assert await fetcher.get_chain_tvl("Ethereum") == {"tvl": 5}
    key = redis.set.await_args.args[0]
    assert "chain_tvl" in key


async def test_stablecoins_endpoint():
    payload = {"peggedAssets": [{"name": "USDT"}]}
    fetcher = DeFiLlamaFetcher(session=_RecordingSession(payload))

    assert await fetcher.get_stablecoins() == payload


async def test_yields_endpoint_returns_the_data_array_without_redis():
    payload = {"data": [{"pool": "a"}, {"pool": "b"}]}
    fetcher = DeFiLlamaFetcher(session=_RecordingSession(payload))

    assert await fetcher.get_yields() == payload["data"]


async def test_yields_payload_without_data_returns_empty_list():
    fetcher = DeFiLlamaFetcher(session=_RecordingSession({"status": "error"}))

    assert await fetcher.get_yields() == []


async def test_yields_are_cached_when_redis_is_present():
    from unittest.mock import AsyncMock

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    payload = {"data": [{"pool": "a"}]}
    fetcher = DeFiLlamaFetcher(session=_RecordingSession(payload), redis_client=redis)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 3600

    assert await fetcher.get_yields() == payload["data"]
    redis.set.assert_awaited_once()
