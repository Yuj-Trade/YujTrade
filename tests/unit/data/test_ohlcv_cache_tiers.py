from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from data.data_provider import MarketDataProvider
from data.ohlcv_store import OhlcvStore


def _provider(redis_client=None, store=None):
    provider = MarketDataProvider(MagicMock(), MagicMock())
    provider.session = MagicMock()
    provider.session.closed = False
    provider.redis = redis_client
    provider.ohlcv_store = store
    provider.config_manager.get_cache_ttl.return_value = 300
    provider.config_manager.get.return_value = 2
    provider.binance_fetcher = AsyncMock()
    provider.coindesk_fetcher = None
    return provider


@pytest.fixture
async def store(tmp_path):
    instance = OhlcvStore(path=tmp_path / "ohlcv.db", max_rows_per_series=0)
    yield instance
    await instance.close()


async def test_store_answers_when_redis_is_unavailable(store, valid_1h_ohlcv):
    await store.write_many("BTC/USDT", "1h", valid_1h_ohlcv)
    provider = _provider(redis_client=None, store=store)

    result = await provider.fetch_ohlcv_data("BTC/USDT", "1h", limit=600)

    assert result is not None
    assert len(result) == 600
    provider.binance_fetcher.get_historical_ohlc.assert_not_called()


async def test_network_result_backfills_store_and_redis(store, valid_1h_ohlcv):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    provider = _provider(redis_client=redis, store=store)
    provider.binance_fetcher.get_historical_ohlc = AsyncMock(return_value=valid_1h_ohlcv)

    result = await provider.fetch_ohlcv_data("BTC/USDT", "1h", limit=600)

    assert result is not None
    redis.set.assert_awaited_once()
    coverage = await store.coverage("BTC/USDT", "1h")
    assert coverage["rows"] == 600


async def test_stale_store_is_refetched(store, valid_1h_ohlcv):
    stale = valid_1h_ohlcv.copy()
    stale.index = pd.date_range(end="2020-01-01", periods=len(stale), freq="1h", tz="UTC")
    await store.write_many("BTC/USDT", "1h", stale)

    provider = _provider(redis_client=None, store=store)
    provider.binance_fetcher.get_historical_ohlc = AsyncMock(return_value=valid_1h_ohlcv)

    result = await provider.fetch_ohlcv_data("BTC/USDT", "1h", limit=600)

    provider.binance_fetcher.get_historical_ohlc.assert_awaited_once()
    assert result.index[-1] > pd.Timestamp("2021-01-01", tz="UTC")


async def test_redis_payload_round_trips_timestamps(store, valid_1h_ohlcv):
    captured = {}

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    async def _set(key, value, ex=None):
        captured["payload"] = value

    redis.set = AsyncMock(side_effect=_set)
    provider = _provider(redis_client=redis, store=store)
    provider.binance_fetcher.get_historical_ohlc = AsyncMock(return_value=valid_1h_ohlcv)

    await provider.fetch_ohlcv_data("BTC/USDT", "1h", limit=600)

    payload = pd.read_json(StringIO(captured["payload"]), orient="split")
    timestamps = pd.to_datetime(payload["timestamp"], unit="ms", utc=True)
    assert timestamps.iloc[-1] == valid_1h_ohlcv.index[-1].as_unit("ms")
    assert timestamps.iloc[0] == valid_1h_ohlcv.index[0].as_unit("ms")


async def test_short_cached_payload_is_not_served(store, valid_1h_ohlcv):
    payload = valid_1h_ohlcv.tail(100).reset_index(drop=True)
    payload.insert(0, "timestamp", valid_1h_ohlcv.tail(100).index.as_unit("ms").asi8)

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=payload.to_json(orient="split"))
    provider = _provider(redis_client=redis, store=store)
    provider.binance_fetcher.get_historical_ohlc = AsyncMock(return_value=valid_1h_ohlcv)

    result = await provider.fetch_ohlcv_data("BTC/USDT", "1h", limit=600)

    provider.binance_fetcher.get_historical_ohlc.assert_awaited_once()
    assert len(result) == 600


async def test_prewarm_covers_the_configured_matrix(store, valid_1h_ohlcv):
    provider = _provider(redis_client=None, store=store)
    provider.binance_fetcher.get_historical_ohlc = AsyncMock(return_value=valid_1h_ohlcv)

    filled = await provider.prewarm_ohlcv_store(["BTC/USDT", "ETH/USDT"], ["1h"], limit=600)

    assert filled == {"BTC/USDT-1h": 600, "ETH/USDT-1h": 600}
    assert (await store.coverage("ETH/USDT", "1h"))["rows"] == 600


async def test_prewarm_without_a_store_is_a_no_op():
    provider = _provider(redis_client=None, store=None)

    assert await provider.prewarm_ohlcv_store(["BTC/USDT"], ["1h"]) == {}
