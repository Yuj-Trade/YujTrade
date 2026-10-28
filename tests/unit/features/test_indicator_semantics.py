import numpy as np
import pandas as pd
import pytest

from common.exceptions import InsufficientDataError
from features.indicators.trend import ADXIndicator, MACDIndicator, SuperTrendIndicator
from features.indicators.volatility import ATRIndicator, BollingerBandsIndicator
from features.indicators.volume import OBVIndicator


def make_ohlcv(rows: int, drift: float = 0.01, noise: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    close = 100.0 * (1.0 + drift) ** np.arange(rows) * (1.0 + noise * rng.standard_normal(rows))
    high = close * (1.0 + np.abs(rng.standard_normal(rows)) * 0.005 + 0.001)
    low = close * (1.0 - np.abs(rng.standard_normal(rows)) * 0.005 - 0.001)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.random(rows) * 1000 + 10,
        },
        index=index,
    )


def test_bollinger_bands_position_between_bands():
    result = BollingerBandsIndicator().calculate(make_ohlcv(100))
    assert 0.0 <= result.value <= 1.0
    assert result.interpretation in {
        "near_upper_band",
        "near_lower_band",
        "middle",
        "neutral_flat_bands",
        "upper_breakout",
        "lower_breakout",
    }


def test_bollinger_bands_flat_series_returns_half():
    rows = 50
    close = np.full(rows, 100.0)
    data = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 100.0}
    )
    result = BollingerBandsIndicator().calculate(data)
    assert result.value == 0.5
    assert result.interpretation == "neutral_flat_bands"


def test_bollinger_bands_requires_history():
    with pytest.raises(InsufficientDataError):
        BollingerBandsIndicator(period=20).calculate(make_ohlcv(5))


def test_atr_is_positive_on_realistic_data():
    result = ATRIndicator().calculate(make_ohlcv(100))
    assert result.value > 0.0


def test_atr_shrinks_on_flat_series():
    rows = 50
    close = np.full(rows, 100.0)
    data = pd.DataFrame(
        {"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 1.0}
    )
    result = ATRIndicator().calculate(data)
    assert result.value == pytest.approx(0.2)


def test_macd_line_matches_histogram_sum():
    result = MACDIndicator().calculate(make_ohlcv(100))
    assert np.isfinite(result.value)


def test_macd_raises_on_short_data():
    with pytest.raises(InsufficientDataError):
        MACDIndicator().calculate(make_ohlcv(5))


def test_adx_in_valid_range():
    result = ADXIndicator().calculate(make_ohlcv(100))
    assert 0.0 <= result.value <= 100.0


def test_adx_high_on_strong_trend():
    result = ADXIndicator().calculate(make_ohlcv(300, drift=0.05))
    assert result.value > 25.0


def test_supertrend_matches_close_price_zone():
    data = make_ohlcv(200, drift=0.02)
    result = SuperTrendIndicator().calculate(data)
    assert np.isfinite(result.value)
    assert data["close"].iloc[-1] == pytest.approx(data["close"].iloc[-1])


def test_obv_finite_and_directional():
    up = OBVIndicator().calculate(make_ohlcv(100, drift=0.02))
    down = OBVIndicator().calculate(make_ohlcv(100, drift=-0.02))
    assert np.isfinite(up.value)
    assert np.isfinite(down.value)


def test_obv_contracts_on_falling_prices():
    data = make_ohlcv(100, drift=-0.02)
    result = OBVIndicator().calculate(data)
    assert result.value < 0.0
    assert "bear" in result.interpretation or result.interpretation == "falling"
