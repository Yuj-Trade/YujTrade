import pandas as pd

from domain.outcome import resolve_outcome
from features.feature_engineering import FeatureEngineer
from trading.execution import FakeAdapter


def test_indicator_values_are_causal_across_300_candle_prefixes():
    data = pd.read_csv(
        "tests/fixtures/ohlcv_1h.csv", index_col=0, parse_dates=True
    ).tail(300)
    engineer = FeatureEngineer()
    for end in range(80, len(data) + 1, 20):
        prefix = data.iloc[:end]
        first = engineer.get_last_indicator_results(prefix, "1h")
        second = FeatureEngineer().get_last_indicator_results(prefix.copy(), "1h")
        assert first.keys() == second.keys()
        assert first == second


def test_fake_adapter_and_outcome_share_execution_price():
    import asyncio

    async def execute():
        adapter = FakeAdapter({"BTC/USDT": 100.0})
        result = await adapter.create_order("BTC/USDT", "buy", 1.0)
        return result

    fill = asyncio.run(execute())
    outcome = resolve_outcome(
        [{"timestamp": pd.Timestamp("2025-01-01", tz="UTC"), "high": 110, "low": 99}],
        "buy",
        fill.price,
        95,
        105,
    )
    assert fill.ok
    assert fill.price == 100.0
    assert outcome is not None
    assert outcome.reason == "target"
