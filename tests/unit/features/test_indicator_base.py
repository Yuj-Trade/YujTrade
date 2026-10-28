import numpy as np
import pandas as pd
import pytest

from common.core import IndicatorResult
from common.exceptions import InsufficientDataError
from features.indicators.base import (
    TechnicalIndicator,
    finite_column,
    last_finite_value,
)
from features.indicators.momentum import RSIIndicator


def make_ohlcv(rows: int, drift: float = 0.01) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    close = 100.0 * (1.0 + drift) ** np.arange(rows)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": np.linspace(1000.0, 2000.0, rows),
        },
        index=index,
    )


@pytest.fixture(scope="module")
def ohlcv() -> pd.DataFrame:
    return make_ohlcv(300)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("text", None),
        (np.nan, None),
        (float("inf"), float("inf")),
        (5, 5.0),
        (5.5, 5.5),
    ],
)
def test_last_finite_value_scalars(value, expected):
    assert last_finite_value(value) == expected


def test_last_finite_value_series_skips_nan():
    series = pd.Series([1.0, 2.0, np.nan])
    assert last_finite_value(series) == 2.0


def test_last_finite_value_series_all_nan():
    assert last_finite_value(pd.Series([np.nan, np.nan])) is None


def test_last_finite_value_empty_series():
    assert last_finite_value(pd.Series([], dtype=float)) is None


def test_last_finite_value_dataframe_first_non_nan_last_row():
    frame = pd.DataFrame({"a": [1.0, np.nan], "b": [2.0, 3.0]})
    assert last_finite_value(frame) == 3.0


def test_last_finite_value_dataframe_all_nan():
    frame = pd.DataFrame({"a": [np.nan]})
    assert last_finite_value(frame) is None


def test_last_finite_value_empty_dataframe():
    assert last_finite_value(pd.DataFrame()) is None


def test_last_finite_value_array_uses_last_finite():
    assert last_finite_value(np.array([1.0, np.nan, 2.0])) == 2.0


def test_last_finite_value_array_all_nan():
    assert last_finite_value(np.array([np.nan, np.nan])) is None


def test_finite_column_indexes_last_row():
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    assert finite_column(frame, 0) == 2.0
    assert finite_column(frame, 1) == 4.0


def test_finite_column_out_of_range():
    frame = pd.DataFrame({"a": [1.0]})
    assert finite_column(frame, 5) is None


def test_finite_column_nan_value():
    frame = pd.DataFrame({"a": [np.nan]})
    assert finite_column(frame, 0) is None


def test_finite_column_bad_inputs():
    assert finite_column(None, 0) is None
    assert finite_column(pd.DataFrame(), 0) is None


def test_technical_indicator_is_abstract():
    with pytest.raises(TypeError):
        TechnicalIndicator()


def test_rsi_raises_on_insufficient_data():
    with pytest.raises(InsufficientDataError):
        RSIIndicator(period=50).calculate(make_ohlcv(10))


def test_rsi_uptrend_is_overbought():
    result = RSIIndicator().calculate(make_ohlcv(300, drift=0.03))
    assert isinstance(result, IndicatorResult)
    assert result.value > 70.0
    assert result.interpretation == "overbought"


def test_rsi_downtrend_is_oversold():
    result = RSIIndicator().calculate(make_ohlcv(300, drift=-0.03))
    assert result.value < 30.0
    assert result.interpretation == "oversold"


def test_rsi_oscillating_series_is_neutral():
    index = np.arange(200)
    data = pd.DataFrame({"close": 100.0 + 5.0 * np.sin(2 * np.pi * index / 20)})
    result = RSIIndicator().calculate(data)
    assert result.interpretation == "neutral"
    assert 30.0 < result.value < 70.0
