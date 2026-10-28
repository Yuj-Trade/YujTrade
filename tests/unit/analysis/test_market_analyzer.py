import numpy as np
import pandas as pd
import pytest

from analysis.market_analyzer import (
    MarketConditionAnalyzer,
    PatternAnalyzer,
    VolumeAnalyzer,
)
from common.core import MarketAnalysis, MarketCondition


def make_ohlcv(rows: int, start: float = 100.0, drift: float = 0.001) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    close = start + drift * np.arange(rows)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.linspace(500.0, 1500.0, rows),
        },
        index=index,
    )


@pytest.fixture
def analyzer() -> MarketConditionAnalyzer:
    return MarketConditionAnalyzer()


@pytest.mark.parametrize(
    ("rows", "drift", "expected"),
    [
        (49, 1.0, "sideways"),
        (60, 1.0, "bullish"),
        (60, -1.0, "bearish"),
        (60, 0.0, "sideways"),
    ],
)
def test_determine_trend(analyzer, rows, drift, expected):
    result = analyzer._determine_trend(make_ohlcv(rows, drift=drift))
    assert result.value == expected


def test_trend_strength_weak_for_short_data(analyzer):
    assert analyzer._calculate_trend_strength(make_ohlcv(10)).value == "weak"


def test_trend_strength_in_valid_set_for_long_data(analyzer):
    result = analyzer._calculate_trend_strength(make_ohlcv(300))
    assert result.value in {"weak", "moderate", "strong"}


def test_volatility_zero_for_short_data(analyzer):
    assert analyzer._calculate_volatility(make_ohlcv(5)) == 0.0


def test_volatility_positive_for_long_data(analyzer):
    assert analyzer._calculate_volatility(make_ohlcv(300)) > 0.0


def test_momentum_zero_for_short_data(analyzer):
    assert analyzer._calculate_momentum(make_ohlcv(5)) == 0.0


def test_momentum_positive_in_uptrend(analyzer):
    assert analyzer._calculate_momentum(make_ohlcv(300)) > 0.0


def test_momentum_negative_in_downtrend(analyzer):
    assert analyzer._calculate_momentum(make_ohlcv(300, drift=-0.01)) < 0.0


def test_hurst_none_for_short_series(analyzer):
    assert analyzer._calculate_hurst_exponent(make_ohlcv(50)["close"]) is None


def test_hurst_finite_for_long_series(analyzer):
    hurst = analyzer._calculate_hurst_exponent(make_ohlcv(300)["close"])
    assert hurst is not None
    assert np.isfinite(hurst)


def test_support_resistance_pair_for_short_data(analyzer):
    assert analyzer._calculate_support_resistance(make_ohlcv(10)) == (None, None)


def test_adx_default_for_short_data(analyzer):
    assert analyzer._calculate_adx(make_ohlcv(10)) == 25.0


def test_trend_acceleration_zero_for_short_data(analyzer):
    assert analyzer._calculate_trend_acceleration(make_ohlcv(5)) == 0.0


def test_volume_ratio_above_one_in_rising_volume(analyzer):
    ratio = VolumeAnalyzer().analyze_volume_pattern(make_ohlcv(100))["volume_ratio"]
    assert ratio > 1.0


def test_volume_pattern_empty_for_short_data():
    assert VolumeAnalyzer().analyze_volume_pattern(make_ohlcv(5)) == {}


def test_volume_pattern_empty_for_missing_volume_column():
    data = make_ohlcv(20).drop(columns=["volume"])
    assert VolumeAnalyzer().analyze_volume_pattern(data) == {}


def test_volume_pattern_empty_for_all_null_volume():
    data = make_ohlcv(20)
    data["volume"] = None
    assert VolumeAnalyzer().analyze_volume_pattern(data) == {}


def test_patterns_empty_for_short_data():
    assert PatternAnalyzer.detect_patterns(make_ohlcv(2)) == []


def test_patterns_return_list_for_long_data():
    patterns = PatternAnalyzer.detect_patterns(make_ohlcv(100))
    assert isinstance(patterns, list)


def test_divergence_empty_for_short_data():
    data = make_ohlcv(5)
    indicator = pd.Series(np.arange(5), index=data.index)
    assert PatternAnalyzer.detect_divergence(data, indicator) == []


def test_divergence_finds_bullish_setup():
    rows = 80
    close = np.full(rows, 100.0)
    close[20] = 90.0
    close[55] = 94.0
    index = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        },
        index=index,
    )
    falling_rsi = pd.Series(np.linspace(60, 20, rows), index=index)
    patterns = PatternAnalyzer.detect_divergence(data, falling_rsi)
    assert "bullish_divergence_A" in patterns


def test_analyze_market_condition_smoke(analyzer):
    data = make_ohlcv(300)
    analysis = analyzer.analyze_market_condition(data)
    assert isinstance(analysis, MarketAnalysis)
    assert analysis.trend.value in {"bullish", "bearish", "sideways"}
    assert analysis.trend_strength.value in {"weak", "moderate", "strong"}
    assert analysis.hurst_exponent is not None
    assert isinstance(analysis.volume_ratio, float)
    assert analysis.market_condition in set(MarketCondition)
    assert isinstance(analysis.candle_patterns, list)
    assert analysis.volatility >= 0.0


def test_analyze_market_condition_rejects_unknown_kwargs(analyzer):
    data = make_ohlcv(300)
    with pytest.raises(TypeError):
        analyzer.analyze_market_condition(data, extra_field="x")
