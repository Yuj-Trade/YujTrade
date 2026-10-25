import json
from unittest.mock import AsyncMock

from data.sources.alphavantage_fetcher import AlphaVantageFetcher


def _fetcher(api_key="test-key", redis_client=None):
    fetcher = AlphaVantageFetcher(api_key=api_key, redis_client=redis_client)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 86400
    return fetcher


def _payload(value):
    return {"data": [{"date": "2024-01-01", "value": str(value)}]}


async def test_macro_data_maps_every_function(monkeypatch):
    fetcher = _fetcher()
    by_function = {
        "CPI": 3.2,
        "FEDERAL_FUNDS_RATE": 4.5,
        "REAL_GDP": 27000.0,
        "UNEMPLOYMENT": 4.1,
        "TREASURY_YIELD": 4.2,
        "INFLATION": 3.0,
        "CONSUMER_SENTIMENT": 68.0,
        "RETAIL_SALES": 700000.0,
    }

    async def _fake(url, params=None, headers=None, limiter=None, endpoint_name="default"):
        return _payload(by_function[params["function"]])

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    result = await fetcher.get_macro_economic_data()

    assert result["CPI"] == 3.2
    assert result["FED_RATE"] == 4.5
    assert result["GDP"] == 27000.0
    assert result["UNEMPLOYMENT"] == 4.1
    assert result["TREASURY_YIELD_10Y"] == 4.2
    assert result["INFLATION"] == 3.0
    assert result["CONSUMER_SENTIMENT"] == 68.0
    assert result["RETAIL_SALES"] == 700000.0


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


async def test_empty_data_array_is_ignored(monkeypatch):
    fetcher = _fetcher()

    async def _fake(url, params=None, **kwargs):
        return {"data": []}

    monkeypatch.setattr(fetcher, "_fetch_json", _fake)

    assert await fetcher.get_macro_economic_data() == {}


async def test_macro_data_is_cached(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=_payload(2.0)))

    await fetcher.get_macro_economic_data()

    redis.set.assert_awaited_once()
    assert json.loads(redis.set.await_args.args[1])["CPI"] == 2.0


async def test_macro_cache_hit_skips_the_requests(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps({"CPI": 9.9}))
    fetcher = _fetcher(redis_client=redis)
    request = AsyncMock()
    monkeypatch.setattr(fetcher, "_fetch_json", request)

    assert await fetcher.get_macro_economic_data() == {"CPI": 9.9}
    request.assert_not_awaited()


async def test_comprehensive_macro_data_uses_its_own_cache_key(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(fetcher, "_fetch_json", AsyncMock(return_value=_payload(5.0)))

    result = await fetcher.get_comprehensive_macro_data()

    assert result["CPI"] == 5.0
    key = redis.set.await_args.args[0]
    assert "comprehensive" in key


async def test_comprehensive_macro_without_a_key_returns_empty(monkeypatch):
    fetcher = _fetcher(api_key="")

    assert await fetcher.get_comprehensive_macro_data() == {}


async def test_closed_fetcher_is_rejected():
    fetcher = _fetcher()
    await fetcher.close()

    from common.exceptions import ObjectClosedError

    try:
        await fetcher.get_comprehensive_macro_data()
    except ObjectClosedError:
        return
    raise AssertionError("expected ObjectClosedError")
