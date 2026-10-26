import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from data.sources.marketindices_fetcher import MarketIndicesFetcher

GLOBAL = {
    "data": {
        "market_cap_percentage": {"btc": 50.0, "eth": 20.0, "usdt": 5.0},
        "total_market_cap": {"usd": 1_000_000.0},
    }
}


def _fetcher(redis_client=None):
    coingecko = MagicMock()
    coingecko.base_url = "https://api.coingecko.com/api/v3"
    coingecko._fetch_json = AsyncMock(return_value=GLOBAL)
    defillama = MagicMock()
    defillama.get_total_tvl_for_chains = AsyncMock(
        return_value=[{"name": "Ethereum", "tvl": 100.0}, {"name": "Solana", "tvl": 50.0}]
    )
    yfinance = MagicMock()
    yfinance.get_traditional_indices = AsyncMock(return_value={"SPX": 5000.0})

    fetcher = MarketIndicesFetcher(
        coingecko_fetcher=coingecko,
        defillama_fetcher=defillama,
        yfinance_fetcher=yfinance,
        redis_client=redis_client,
    )
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 600
    return fetcher


class TestCryptoIndices:
    async def test_dominance_and_cap_derivatives_are_computed(self):
        indices = await _fetcher().get_crypto_indices()

        assert indices["BTC.D"] == 50.0
        assert indices["ETH.D"] == 20.0
        assert indices["TOTAL"] == 1_000_000.0
        assert indices["TOTAL2"] == pytest.approx(500_000.0)
        assert indices["TOTAL3"] == pytest.approx(300_000.0)
        assert indices["OTHERS.D"] == pytest.approx(25.0)
        assert indices["DEFI_TVL"] == pytest.approx(150.0)

    async def test_global_failure_still_returns_tvl(self):
        fetcher = _fetcher()
        fetcher.coingecko._fetch_json = AsyncMock(side_effect=RuntimeError("down"))

        indices = await fetcher.get_crypto_indices()

        assert indices == {"DEFI_TVL": pytest.approx(150.0)}

    async def test_empty_global_payload_is_ignored(self):
        fetcher = _fetcher()
        fetcher.coingecko._fetch_json = AsyncMock(return_value={})

        indices = await fetcher.get_crypto_indices()

        assert "BTC.D" not in indices

    async def test_cache_hit_short_circuits(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"BTC.D": 1.0}))
        fetcher = _fetcher(redis_client=redis)

        assert await fetcher.get_crypto_indices() == {"BTC.D": 1.0}
        fetcher.coingecko._fetch_json.assert_not_awaited()

    async def test_result_is_cached(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        fetcher = _fetcher(redis_client=redis)

        await fetcher.get_crypto_indices()

        redis.set.assert_awaited_once()

    async def test_cache_failure_does_not_break_the_result(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=RuntimeError("redis down"))
        redis.set = AsyncMock(side_effect=RuntimeError("redis down"))
        fetcher = _fetcher(redis_client=redis)

        indices = await fetcher.get_crypto_indices()

        assert indices["BTC.D"] == 50.0


class TestAllIndices:
    async def test_every_source_is_merged(self):
        indices = await _fetcher().get_all_indices()

        assert indices["BTC.D"] == 50.0
        assert indices["SPX"] == 5000.0

    async def test_macro_is_not_fetched_through_the_indices_path(self):
        indices = await _fetcher().get_all_indices()

        assert "CPI" not in indices
        assert "FED_RATE" not in indices

    async def test_failing_sources_are_skipped(self):
        fetcher = _fetcher()
        fetcher.yfinance.get_traditional_indices = AsyncMock(side_effect=RuntimeError("down"))

        indices = await fetcher.get_all_indices()

        assert "SPX" not in indices
        assert indices["BTC.D"] == 50.0


async def test_closed_fetcher_is_rejected():
    fetcher = _fetcher()
    await fetcher.close()

    with pytest.raises(RuntimeError, match="closed"):
        await fetcher.get_crypto_indices()
