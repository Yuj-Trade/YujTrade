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
    assert provider.calls["get_derivatives_data"] == 3
    assert provider.calls["get_order_book"] == 3


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
