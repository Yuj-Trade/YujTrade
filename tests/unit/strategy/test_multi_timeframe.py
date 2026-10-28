from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from common.core import (
    MarketAnalysis,
    MarketCondition,
    SignalType,
    TrendDirection,
    TrendStrength,
)


def make_analysis(trend: TrendDirection, strength: TrendStrength) -> MarketAnalysis:
    return MarketAnalysis(
        trend=trend,
        trend_strength=strength,
        volatility=2.0,
        volume_trend="increasing",
        support_levels=[],
        resistance_levels=[],
        momentum_score=0.0,
        market_condition=MarketCondition.NEUTRAL,
        trend_acceleration=0.0,
        volume_confirmation=False,
    )


def dummy_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.0] * 5,
            "volume": [10.0] * 5,
        }
    )


from strategy.multi_timeframe import MultiTimeframeAnalyzer  # noqa: E402


@pytest.fixture(scope="module")
def base_frame() -> pd.DataFrame:
    return dummy_frame()


@pytest.fixture(scope="module")
def analyzer() -> MultiTimeframeAnalyzer:
    return MultiTimeframeAnalyzer(MagicMock())


@pytest.fixture
def aligned_analyzer(analyzer) -> MultiTimeframeAnalyzer:
    analyzer._get_higher_tf_data = AsyncMock(return_value=dummy_frame())
    analyzer.analyzer.analyze_market_condition = MagicMock(
        return_value=make_analysis(TrendDirection.BULLISH, TrendStrength.WEAK)
    )
    return analyzer


@pytest.mark.parametrize("timeframe", ["1M", "5m", "unknown"])
async def test_top_or_unknown_timeframe_returns_neutral_one(analyzer, timeframe, base_frame):
    score, analyses, conflict = await analyzer.get_confirmation_score(
        "BTC/USDT", timeframe, SignalType.BUY, base_frame
    )
    assert score == 1.0
    assert analyses == {}
    assert conflict is False


@pytest.mark.parametrize(
    ("signal_type", "trend", "expected"),
    [
        (SignalType.BUY, TrendDirection.BULLISH, 0.7),
        (SignalType.SELL, TrendDirection.BEARISH, 0.7),
        (SignalType.BUY, TrendDirection.BEARISH, 0.0),
        (SignalType.SELL, TrendDirection.BULLISH, 0.0),
        (SignalType.BUY, TrendDirection.SIDEWAYS, 0.4),
    ],
)
def test_single_tf_score_direction_matrix(analyzer, signal_type, trend, expected):
    score, _ = analyzer._calculate_single_tf_score(
        make_analysis(trend, TrendStrength.WEAK), signal_type
    )
    assert score == pytest.approx(expected)


def test_single_tf_score_aligned_with_moderate_strength(analyzer):
    score, _ = analyzer._calculate_single_tf_score(
        make_analysis(TrendDirection.BULLISH, TrendStrength.MODERATE), SignalType.BUY
    )
    assert score == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("signal_type", "trend"),
    [
        (SignalType.BUY, TrendDirection.BEARISH),
        (SignalType.SELL, TrendDirection.BULLISH),
    ],
)
def test_single_tf_score_opposed_trends_conflict(analyzer, signal_type, trend):
    score, conflict = analyzer._calculate_single_tf_score(
        make_analysis(trend, TrendStrength.WEAK), signal_type
    )
    assert score == pytest.approx(0.0)
    assert conflict is True


def test_single_tf_score_volume_confirmation_bonus(analyzer):
    analysis = make_analysis(TrendDirection.BULLISH, TrendStrength.STRONG)
    analysis.volume_confirmation = True
    score, _ = analyzer._calculate_single_tf_score(analysis, SignalType.BUY)
    assert score == pytest.approx(1.0)


async def test_confirmation_weighted_average(aligned_analyzer, base_frame):
    score, analyses, conflict = await aligned_analyzer.get_confirmation_score(
        "BTC/USDT", "1d", SignalType.BUY, base_frame
    )
    assert score == pytest.approx(0.7)
    assert set(analyses) == {"1w", "1M"}
    assert conflict is False
    assert aligned_analyzer._get_higher_tf_data.await_count == 2


async def test_confirmation_reports_conflict(analyzer, base_frame):
    analyzer._get_higher_tf_data = AsyncMock(return_value=dummy_frame())
    analyzer.analyzer.analyze_market_condition = MagicMock(
        return_value=make_analysis(TrendDirection.BEARISH, TrendStrength.WEAK)
    )
    score, analyses, conflict = await analyzer.get_confirmation_score(
        "BTC/USDT", "1d", SignalType.BUY, base_frame
    )
    assert conflict is True
    assert score == pytest.approx(0.0)
    assert set(analyses) == {"1w", "1M"}


async def test_empty_higher_tf_data_skipped(analyzer, base_frame):
    analyzer._get_higher_tf_data = AsyncMock(return_value=pd.DataFrame())
    score, analyses, conflict = await analyzer.get_confirmation_score(
        "BTC/USDT", "1d", SignalType.BUY, base_frame
    )
    assert score == 1.0
    assert analyses == {}
    assert conflict is False


async def test_insufficient_data_swallowed(analyzer, base_frame):
    from common.exceptions import InsufficientDataError

    calls = {"n": 0}

    async def higher_tf(symbol, timeframe):
        calls["n"] += 1
        raise InsufficientDataError(f"no data for {timeframe}")

    analyzer._get_higher_tf_data = AsyncMock(side_effect=higher_tf)
    score, analyses, conflict = await analyzer.get_confirmation_score(
        "BTC/USDT", "1d", SignalType.BUY, base_frame
    )
    assert score == 1.0
    assert analyses == {}
    assert conflict is False
    assert calls["n"] == 2


async def test_generic_exception_swallowed(analyzer, base_frame):
    analyzer._get_higher_tf_data = AsyncMock(side_effect=RuntimeError("boom"))
    score, analyses, conflict = await analyzer.get_confirmation_score(
        "BTC/USDT", "1d", SignalType.BUY, base_frame
    )
    assert score == 1.0
    assert analyses == {}


async def test_hold_signal_scores_neutral_for_strong_bullish(analyzer, base_frame):
    analyzer._get_higher_tf_data = AsyncMock(return_value=dummy_frame())
    analyzer.analyzer.analyze_market_condition = MagicMock(
        return_value=make_analysis(TrendDirection.BULLISH, TrendStrength.STRONG)
    )
    score, _, conflict = await analyzer.get_confirmation_score(
        "BTC/USDT", "1d", SignalType.HOLD, base_frame
    )
    assert score == pytest.approx(0.65)
    assert conflict is False
