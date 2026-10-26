import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from common.exceptions import ObjectClosedError
from data.sources.alphavantage_fetcher import MACRO_SERIES, AlphaVantageFetcher


def _fetcher(api_key="test-key", redis_client=None):
    fetcher = AlphaVantageFetcher(api_key=api_key, redis_client=redis_client)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 86400
    return fetcher


def _payload(value):
    return {"data": [{"date": "2024-01-01", "value": str(value)}]}


def test_only_consumed_series_are_requested():
    assert set(MACRO_SERIES) == {
        "CPI",
        "FED_RATE",
        "GDP",
        "UNEMPLOYMENT",
        "TREASURY_YIELD",
    }
    assert len(MACRO_SERIES) <= 5


async def test_macro_data_maps_every_function(monkeypatch):
    fetcher = _fetcher()
    by_function = {
        "CPI": 3.2,
        "FEDERAL_FUNDS_RATE": 4.5,
        "REAL_GDP": 27000.0,
        "UNEMPLOYMENT": 4.1,
        "TREASURY_YIELD": 4.2,
    }

    async def _fake(url, params=None, headers=None, limiter=None, endpoint_name="default"):
        return _payload(by_function[params["function"]])

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    result = await fetcher.get_macro_economic_data()

    assert result == {
        "CPI": 3.2,
        "FED_RATE": 4.5,
        "GDP": 27000.0,
        "UNEMPLOYMENT": 4.1,
        "TREASURY_YIELD": 4.2,
    }


async def test_the_api_key_is_attached_to_every_request(monkeypatch):
    fetcher = _fetcher(api_key="secret-key")
    seen: list[dict] = []

    async def _fake(url, params=None, **kwargs):
        seen.append(params)
        return _payload(1.0)

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    await fetcher.get_macro_economic_data()

    assert len(seen) == 5
    assert all(params["apikey"] == "secret-key" for params in seen)


async def test_missing_api_key_returns_empty_dict_without_a_request(monkeypatch):
    fetcher = _fetcher(api_key="")
    request = AsyncMock()
    monkeypatch.setattr(fetcher, "_fetch_json", request)

    assert await fetcher.get_macro_economic_data() == {}
    request.assert_not_awaited()


async def test_a_failing_function_is_skipped(monkeypatch):
    fetcher = _fetcher()

    async def _fake(url, params=None, **kwargs):
        if params["function"] == "CPI":
            raise ValueError("upstream down")
        return _payload(1.0)

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    result = await fetcher.get_macro_economic_data()

    assert "CPI" not in result
    assert result["FED_RATE"] == 1.0


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {"data": [{"value": "."}]},
        {"data": [{}]},
        {"data": "not-a-list"},
        {"Information": "rate limit"},
        None,
    ],
)
async def test_unusable_payloads_are_ignored(monkeypatch, payload):
    fetcher = _fetcher()
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=payload))

    assert await fetcher.get_macro_economic_data() == {}


async def test_macro_data_is_cached(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=_payload(2.0)))

    await fetcher.get_macro_economic_data()

    redis.set.assert_awaited_once()
    assert json.loads(redis.set.await_args.args[1])["CPI"] == 2.0
    assert redis.set.await_args.kwargs["ex"] == 86400


async def test_macro_cache_hit_skips_the_requests(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps({"CPI": 9.9}))
    fetcher = _fetcher(redis_client=redis)
    request = AsyncMock()
    monkeypatch.setattr(fetcher, "_fetch_json", request)

    assert await fetcher.get_macro_economic_data() == {"CPI": 9.9}
    request.assert_not_awaited()


async def test_a_corrupt_cache_entry_falls_through_to_the_network(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="{not json")
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=_payload(3.0)))

    result = await fetcher.get_macro_economic_data()
    assert result["CPI"] == 3.0


async def test_a_failing_cache_read_falls_through_to_the_network(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=_payload(3.0)))

    result = await fetcher.get_macro_economic_data()
    assert result["CPI"] == 3.0


async def test_a_failing_cache_write_does_not_lose_the_result(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(side_effect=ConnectionError("redis down"))
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=_payload(3.0)))

    result = await fetcher.get_macro_economic_data()
    assert result["CPI"] == 3.0


async def test_concurrent_callers_share_one_fetch(monkeypatch):
    fetcher = _fetcher()
    calls = 0
    release = asyncio.Event()

    async def _fake(url, params=None, **kwargs):
        nonlocal calls
        calls += 1
        await release.wait()
        return _payload(1.0)

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    waiters = [asyncio.ensure_future(fetcher.get_macro_economic_data()) for _ in range(10)]
    await asyncio.sleep(0.05)
    release.set()
    results = await asyncio.gather(*waiters)

    assert calls == 5
    assert all(result["CPI"] == 1.0 for result in results)


async def test_a_later_call_after_completion_refetches(monkeypatch):
    fetcher = _fetcher()
    request = AsyncMock(return_value=_payload(1.0))
    monkeypatch.setattr(fetcher, "_fetch_json", request)

    await fetcher.get_macro_economic_data()
    await fetcher.get_macro_economic_data()

    assert request.await_count == 10


async def test_closed_fetcher_is_rejected():
    fetcher = _fetcher()
    await fetcher.close()

    with pytest.raises(ObjectClosedError):
        await fetcher.get_macro_economic_data()
