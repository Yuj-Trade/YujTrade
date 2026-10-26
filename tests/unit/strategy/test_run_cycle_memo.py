import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import ConfigManager
from strategy.signal_generator import SignalGenerator


@pytest.fixture
def config_manager(tmp_path):
    return ConfigManager(
        config_path=str(tmp_path / "config.json"),
        weights_path=str(tmp_path / "weights.json"),
    )


class CountingProvider:
    def __init__(self):
        self.calls = {
            name: 0
            for name in (
                "get_derivatives_data",
                "get_fundamental_data",
                "get_onchain_data",
                "get_order_book",
                "get_macro_data",
                "get_trending_data",
                "get_all_indices",
                "get_news_sentiment",
            )
        }

    async def _record(self, name, *args):
        self.calls[name] += 1
        return None

    async def get_derivatives_data(self, symbol):
        return await self._record("get_derivatives_data", symbol)

    async def get_fundamental_data(self, symbol):
        return await self._record("get_fundamental_data", symbol)

    async def get_onchain_data(self, symbol):
        return await self._record("get_onchain_data", symbol)

    async def get_order_book(self, symbol):
        return await self._record("get_order_book", symbol)

    async def get_macro_data(self):
        return await self._record("get_macro_data")

    async def get_trending_data(self):
        return await self._record("get_trending_data")

    async def get_all_indices(self):
        return await self._record("get_all_indices")

    async def get_news_sentiment(self, currencies):
        return await self._record("get_news_sentiment", currencies)


def _generator(config_manager, provider):
    model_manager = MagicMock()
    model_manager.predict_with_confidence = AsyncMock(return_value=None)
    return SignalGenerator(provider, model_manager, config_manager)


async def test_within_cycle_static_sources_fetched_once(config_manager, valid_1h_ohlcv):
    provider = CountingProvider()
    generator = _generator(config_manager, provider)

    await generator.begin_run_cycle()
    for _ in range(3):
        await generator.generate_signal(
            "BTC/USDT", "1h", valid_1h_ohlcv, include_external=True, include_ml=False
        )
    await generator.end_run_cycle()

    assert provider.calls["get_fundamental_data"] == 1
    assert provider.calls["get_onchain_data"] == 1
    assert provider.calls["get_macro_data"] == 1
    assert provider.calls["get_trending_data"] == 1
    assert provider.calls["get_all_indices"] == 1
    assert provider.calls["get_derivatives_data"] == 1
    assert provider.calls["get_order_book"] == 1
    assert provider.calls["get_news_sentiment"] == 1


async def test_outside_cycle_every_call_fetches_fresh(config_manager, valid_1h_ohlcv):
    provider = CountingProvider()
    generator = _generator(config_manager, provider)

    for _ in range(2):
        await generator.generate_signal(
            "BTC/USDT", "1h", valid_1h_ohlcv, include_external=True, include_ml=False
        )

    assert provider.calls["get_fundamental_data"] == 2


async def test_end_cycle_clears_memo(config_manager, valid_1h_ohlcv):
    provider = CountingProvider()
    generator = _generator(config_manager, provider)

    await generator.begin_run_cycle()
    await generator.generate_signal(
        "BTC/USDT", "1h", valid_1h_ohlcv, include_external=True, include_ml=False
    )
    await generator.end_run_cycle()
    await generator.generate_signal(
        "BTC/USDT", "1h", valid_1h_ohlcv, include_external=True, include_ml=False
    )

    assert provider.calls["get_fundamental_data"] == 2
    assert provider.calls["get_macro_data"] == 2


class SlowProvider(CountingProvider):
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()
        self.concurrent = 0
        self.max_concurrent = 0

    async def _record(self, name, *args):
        self.calls[name] += 1
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        await self.release.wait()
        self.concurrent -= 1
        return name


async def test_concurrent_symbols_share_one_in_flight_fetch(config_manager):
    provider = SlowProvider()
    generator = _generator(config_manager, provider)
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]

    await generator.begin_run_cycle()
    pending = [asyncio.ensure_future(generator._gather_external_data(s)) for s in symbols]
    await asyncio.sleep(0.05)
    provider.release.set()
    results = await asyncio.gather(*pending)
    await generator.end_run_cycle()

    assert provider.calls["get_macro_data"] == 1
    assert provider.calls["get_trending_data"] == 1
    assert provider.calls["get_all_indices"] == 1
    assert provider.calls["get_fundamental_data"] == len(symbols)
    assert all(result["macro"] == "get_macro_data" for result in results)


class FailingProvider(CountingProvider):
    async def get_macro_data(self):
        self.calls["get_macro_data"] += 1
        raise RuntimeError("alphavantage down")


async def test_a_failed_source_is_reported_once_per_cycle(config_manager, monkeypatch):
    provider = FailingProvider()
    generator = _generator(config_manager, provider)
    warnings: list[str] = []

    from config.logger import logger as configured_logger

    handler_id = configured_logger.add(
        lambda m: warnings.append(m.record["message"]), format="{message}", level="WARNING"
    )
    try:
        await generator.begin_run_cycle()
        for symbol in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            await generator._gather_external_data(symbol)
        await generator.end_run_cycle()
    finally:
        configured_logger.remove(handler_id)

    assert provider.calls["get_macro_data"] == 1
    assert len([w for w in warnings if "Failed to fetch macro" in w]) == 1


async def test_news_is_fetched_once_per_base_asset(config_manager):
    provider = CountingProvider()
    generator = _generator(config_manager, provider)

    await generator.begin_run_cycle()
    await generator._gather_external_data("BTC/USDT")
    await generator._gather_external_data("BTC/USDT")
    await generator._gather_external_data("ETH/USDT")
    await generator.end_run_cycle()

    assert provider.calls["get_news_sentiment"] == 2


async def test_pending_fetches_are_cancelled_when_the_cycle_ends(config_manager):
    provider = SlowProvider()
    generator = _generator(config_manager, provider)

    await generator.begin_run_cycle()
    task = asyncio.ensure_future(generator._gather_external_data("BTC/USDT"))
    await asyncio.sleep(0.05)
    await generator.end_run_cycle()
    task.cancel()

    assert generator._cycle_memo is None
