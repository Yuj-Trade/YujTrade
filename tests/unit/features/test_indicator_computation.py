import numpy as np
import pandas as pd
import pytest

from features.indicators.factory import IndicatorFactory

ALL_INDICATORS = sorted(IndicatorFactory().get_all_indicator_names())


@pytest.fixture(scope="module")
def ohlcv():
    rng = np.random.default_rng(7)
    n = 300
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    close = pd.Series(100 + np.cumsum(rng.standard_normal(n)), index=index)
    return pd.DataFrame(
        {
            "open": close.shift(1).bfill(),
            "high": close + np.abs(rng.standard_normal(n)),
            "low": close - np.abs(rng.standard_normal(n)),
            "close": close,
            "volume": pd.Series(rng.random(n) * 1000 + 10, index=index),
        },
        index=index,
    )


@pytest.mark.parametrize("name", ALL_INDICATORS)
def test_indicator_returns_a_finite_value(name, ohlcv):
    result = IndicatorFactory().create(name).calculate(ohlcv)
    assert result is not None
    assert isinstance(result.value, float)
    assert np.isfinite(result.value)


@pytest.mark.parametrize("name", ["supertrend", "psar", "ichimoku"])
def test_weighted_trend_indicators_are_computed(name, ohlcv):
    result = IndicatorFactory().create(name).calculate(ohlcv)
    assert np.isfinite(float(result.value))


@pytest.mark.parametrize("name", ["qqe", "gann_hilo", "pvi", "rvi"])
def test_multi_column_sources_yield_a_scalar(name, ohlcv):
    result = IndicatorFactory().create(name).calculate(ohlcv)
    assert isinstance(result.value, float)
    assert np.isfinite(result.value)
