import importlib

import numpy as np
import pandas as pd
import pytest

from common.core import IndicatorResult
from features.indicators.base import TechnicalIndicator

MODULES = ["custom", "cycle", "momentum", "trend", "volatility", "volume"]


def make_ohlcv(rows: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    close = pd.Series(100 + np.cumsum(rng.standard_normal(rows)), index=index)
    return pd.DataFrame(
        {
            "open": close.shift(1).bfill(),
            "high": close + np.abs(rng.standard_normal(rows)),
            "low": close - np.abs(rng.standard_normal(rows)),
            "close": close,
            "volume": pd.Series(rng.random(rows) * 1000 + 10, index=index),
        },
        index=index,
    )


@pytest.fixture(scope="module")
def ohlcv() -> pd.DataFrame:
    return make_ohlcv()


def instantiable_indicators(module_name: str) -> list[TechnicalIndicator]:
    module = importlib.import_module(f"features.indicators.{module_name}")
    indicators = []
    for name in vars(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, TechnicalIndicator)
            and obj is not TechnicalIndicator
            and not getattr(obj, "__abstractmethods__", None)
        ):
            try:
                indicators.append(obj())
            except TypeError:
                continue
    assert indicators, module_name
    return indicators


@pytest.mark.parametrize("module_name", MODULES)
def test_module_indicator_class_names_unique(module_name):
    names = [type(i).__name__ for i in instantiable_indicators(module_name)]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("module_name", MODULES)
def test_module_indicators_compute_finite_values(module_name, ohlcv):
    for indicator in instantiable_indicators(module_name):
        result = indicator.calculate(ohlcv)
        assert isinstance(result, IndicatorResult), type(indicator).__name__
        assert isinstance(result.value, float), type(indicator).__name__
        assert np.isfinite(result.value), type(indicator).__name__
        assert isinstance(result.interpretation, str), type(indicator).__name__


@pytest.mark.parametrize("module_name", MODULES)
def test_module_indicators_report_name(module_name, ohlcv):
    for indicator in instantiable_indicators(module_name):
        result = indicator.calculate(ohlcv)
        assert isinstance(result.name, str)
        assert result.name


@pytest.mark.parametrize("module_name", MODULES)
def test_module_indicators_are_deterministic(module_name, ohlcv):
    for indicator in instantiable_indicators(module_name):
        first = indicator.calculate(ohlcv)
        second = type(indicator)().calculate(ohlcv)
        assert first.value == second.value, type(indicator).__name__
