from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from analysis.scoring import AnalysisScorer
from common.constants import AnalysisComponent
from common.core import (
    IndicatorResult,
    MarketAnalysis,
    MarketCondition,
    TrendDirection,
    TrendStrength,
)


@pytest.fixture
def config_manager():
    config = MagicMock()
    config.get_component_weights.return_value = {
        "technical_analysis": 0.4,
        "market_context": 0.2,
        "external_data": 0.2,
        "ml_models": 0.2,
    }
    return config


@pytest.fixture
def scorer(config_manager):
    return AnalysisScorer(config_manager)


@pytest.fixture
def market_context():
    return MarketAnalysis(
        trend=TrendDirection.BULLISH,
        trend_strength=TrendStrength.WEAK,
        volatility=2.0,
        volume_trend="stable",
        support_levels=[],
        resistance_levels=[],
        momentum_score=0.0,
        market_condition=MarketCondition.NEUTRAL,
        trend_acceleration=0.0,
        volume_confirmation=False,
    )


def indicator(value: float, interpretation: str, strength: float = 100.0) -> IndicatorResult:
    return IndicatorResult(
        name="rsi", value=value, signal_strength=strength, interpretation=interpretation
    )


def test_score_technical_results_empty_returns_zero(scorer, market_context):
    assert scorer.score_technical_results({}, market_context) == 0.0


def test_score_technical_results_ignores_none_result(scorer, market_context):
    assert scorer.score_technical_results({"rsi": {"result": None}}, market_context) == 0.0


def test_score_technical_results_ignores_missing_value_attr(scorer, market_context):
    payload = {"rsi": {"result": SimpleNamespace(value=None)}}
    assert scorer.score_technical_results(payload, market_context) == 0.0


def test_score_technical_results_ignores_nan_value(scorer, market_context):
    payload = {"rsi": {"result": indicator(float("nan"), "bullish")}}
    assert scorer.score_technical_results(payload, market_context) == 0.0


def test_score_technical_results_weighted_mean(scorer, market_context):
    payload = {
        "rsi": {"result": indicator(30.0, "bullish", 100.0)},
        "macd": {"result": indicator(1.0, "bearish", 100.0)},
    }
    score = scorer.score_technical_results(payload, market_context, weights={"rsi": 3.0})
    assert score == pytest.approx((1.0 * 3.0 - 1.0) / 4.0)


def test_get_indicator_score_bullish_full_strength(scorer, market_context):
    result = indicator(30.0, "RSI shows bullish momentum", 100.0)
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(1.0)


def test_get_indicator_score_bearish(scorer, market_context):
    result = indicator(70.0, "bearish crossover", 100.0)
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(-1.0)


def test_get_indicator_score_conflicting_keywords_cancel(scorer, market_context):
    result = indicator(50.0, "bullish and bearish", 100.0)
    assert scorer.get_indicator_score(result, market_context) == 0.0


def test_get_indicator_score_missing_strength_defaults_half(scorer, market_context):
    result = IndicatorResult(name="rsi", value=30.0, signal_strength=None, interpretation="bullish")
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(0.5)


def test_get_indicator_score_is_case_insensitive(scorer, market_context):
    result = indicator(30.0, "BULLISH BREAKOUT ABOVE support level", 100.0)
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(1.0)


def test_get_indicator_score_bearish_penalized_in_strong_bull(scorer, market_context):
    market_context.trend = TrendDirection.BULLISH
    market_context.trend_strength = TrendStrength.STRONG
    result = indicator(70.0, "bearish", 100.0)
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(-0.5)


def test_get_indicator_score_oversold_exempt_in_strong_bull(scorer, market_context):
    market_context.trend = TrendDirection.BULLISH
    market_context.trend_strength = TrendStrength.STRONG
    result = indicator(25.0, "oversold reversal up", 100.0)
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(1.0)


def test_get_indicator_score_bullish_penalized_in_strong_bear(scorer, market_context):
    market_context.trend = TrendDirection.BEARISH
    market_context.trend_strength = TrendStrength.STRONG
    result = indicator(30.0, "bullish", 100.0)
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(0.5)


def test_get_indicator_score_overbought_exempt_in_strong_bear(scorer, market_context):
    market_context.trend = TrendDirection.BEARISH
    market_context.trend_strength = TrendStrength.STRONG
    result = indicator(75.0, "overbought distribution down", 100.0)
    assert scorer.get_indicator_score(result, market_context) == pytest.approx(-1.0)


def test_score_market_context_bullish_strong_oversold(scorer):
    context = MarketAnalysis(
        trend=TrendDirection.BULLISH,
        trend_strength=TrendStrength.STRONG,
        volatility=2.0,
        volume_trend="increasing",
        support_levels=[],
        resistance_levels=[],
        momentum_score=0.0,
        market_condition=MarketCondition.OVERSOLD,
        trend_acceleration=0.0,
        volume_confirmation=False,
    )
    score, reasons = scorer.score_market_context(context)
    assert score == pytest.approx(0.75)
    assert any("Trend:" in r for r in reasons)


def test_score_market_context_sideways_weak_neutral(scorer):
    context = MarketAnalysis(
        trend=TrendDirection.SIDEWAYS,
        trend_strength=TrendStrength.WEAK,
        volatility=1.0,
        volume_trend="stable",
        support_levels=[],
        resistance_levels=[],
        momentum_score=0.0,
        market_condition=MarketCondition.NEUTRAL,
        trend_acceleration=0.0,
        volume_confirmation=False,
    )
    score, _ = scorer.score_market_context(context)
    assert score == pytest.approx(0.0)


def test_score_market_context_extras_momentum_alignment(scorer):
    context = MarketAnalysis(
        trend=TrendDirection.BULLISH,
        trend_strength=TrendStrength.WEAK,
        volatility=2.0,
        volume_trend="stable",
        support_levels=[],
        resistance_levels=[],
        momentum_score=0.5,
        market_condition=MarketCondition.NEUTRAL,
        trend_acceleration=0.0,
        volume_confirmation=True,
    )
    score, reasons = scorer.score_market_context(context)
    assert score > 0.0
    assert any("Momentum aligned" in r for r in reasons)
    assert any("Volume confirms" in r for r in reasons)


def test_score_market_context_always_within_bounds(scorer, market_context):
    score, _ = scorer.score_market_context(market_context)
    assert -1.0 <= score <= 1.0


def test_unwrap_single_data_key():
    assert AnalysisScorer._unwrap({"data": 5}) == 5


def test_unwrap_passthrough_for_other_dicts():
    assert AnalysisScorer._unwrap({"score": 5}) == {"score": 5}


def test_unwrap_passthrough_for_non_dict():
    assert AnalysisScorer._unwrap("raw") == "raw"


def test_score_external_data_all_none_sources(scorer, market_context):
    data = {
        "news": None,
        "derivatives": None,
        "fundamental": None,
        "onchain": None,
        "order_book": None,
        "macro": None,
        "trending": None,
        "market_indices": None,
    }
    score, reasons = scorer.score_external_data(data, market_context, "BTC/USDT")
    assert score == 0.0
    assert reasons == []


def test_score_external_data_full_bundle(scorer, market_context):
    from common.core import (
        DerivativesAnalysis,
        FundamentalAnalysis,
        MacroEconomicData,
        OnChainAnalysis,
        OrderBook,
        TrendingData,
    )

    data = {
        "news": {"score": 10.0, "fear_greed_index": 10},
        "derivatives": DerivativesAnalysis(
            funding_rate=0.0, taker_long_short_ratio=1.5, open_interest=1
        ),
        "fundamental": FundamentalAnalysis(developer_score=80, community_score=90),
        "onchain": OnChainAnalysis(mvrv=0.5, sopr=0.9),
        "order_book": OrderBook(total_bid_volume=1000, total_ask_volume=500),
        "macro": MacroEconomicData(fed_rate=2.0, cpi=2.0),
        "trending": TrendingData(coingecko_trending=["btc"]),
        "market_indices": {"BTC.D": 65.0, "USDT.D": 9.0, "DXY": 106.0, "VIX": 31.0},
    }
    score, reasons = scorer.score_external_data(data, market_context, "BTC/USDT")
    assert score == 1.0
    assert len(reasons) > 5


def test_score_external_data_fear_greed_extremes(scorer, market_context):
    greedy = {"news": {"score": 0, "fear_greed_index": 80}}
    score, reasons = scorer.score_external_data(greedy, market_context, "BTC/USDT")
    assert score == pytest.approx(-0.15 + 0.0)
    assert any("extreme greed" in r for r in reasons)

    fearful = {"news": {"score": 0, "fear_greed_index": 10}}
    score, reasons = scorer.score_external_data(fearful, market_context, "BTC/USDT")
    assert score == pytest.approx(0.15)


def test_score_external_data_news_score_clamped(scorer, market_context):
    score, _ = scorer.score_external_data({"news": {"score": 100.0}}, market_context, "BTC/USDT")
    assert score == pytest.approx(0.5)
    score, _ = scorer.score_external_data({"news": {"score": -100.0}}, market_context, "BTC/USDT")
    assert score == pytest.approx(-0.5)


def test_score_external_data_derivative_ratio_bands(scorer, market_context):
    from common.core import DerivativesAnalysis

    high = scorer.score_external_data(
        {"derivatives": DerivativesAnalysis(taker_long_short_ratio=1.5, funding_rate=0.0)},
        market_context,
        "BTC/USDT",
    )
    assert high[0] == pytest.approx(0.2)
    low = scorer.score_external_data(
        {"derivatives": DerivativesAnalysis(taker_long_short_ratio=0.5, funding_rate=0.0)},
        market_context,
        "BTC/USDT",
    )
    assert low[0] == pytest.approx(-0.2)
    flat = scorer.score_external_data(
        {"derivatives": DerivativesAnalysis(taker_long_short_ratio=1.0, funding_rate=0.0)},
        market_context,
        "BTC/USDT",
    )
    assert flat[0] == pytest.approx(0.0)


def test_score_external_data_market_indices_for_altcoin(scorer, market_context):
    data = {"market_indices": {"BTC.D": 65.0, "USDT.D": 9.0, "DXY": 106.0, "VIX": 31.0}}
    score, reasons = scorer.score_external_data(data, market_context, "ETH/USDT")
    assert score == pytest.approx(-0.3)
    assert any("BTC dominance" in r for r in reasons)


def test_score_external_data_btc_dominance_ignored_for_btc(scorer, market_context):
    data = {"market_indices": {"BTC.D": 65.0}}
    score, _ = scorer.score_external_data(data, market_context, "BTC/USDT")
    assert score == 0.0


@pytest.mark.parametrize(
    ("funding", "asset", "expected"),
    [
        (0.5, "BTC", -0.3),
        (0.015, "BTC", -0.15),
        (0.01, "BTC", 0.0),
        (-0.5, "BTC", 0.3),
        (-0.001, "BTC", 0.15),
    ],
)
def test_normalize_funding_rate_bands(scorer, market_context, funding, asset, expected):
    result = scorer.normalize_funding_rate(funding, f"{asset}/USDT", market_context)
    assert result == pytest.approx(expected)


def test_score_ml_predictions_empty(scorer):
    assert scorer.score_ml_predictions({}, 100.0) == (0.0, [], 0.0)


def test_score_ml_predictions_single_upward(scorer):
    predictions = {"lstm": {"prediction": 110.0, "confidence": 80.0}}
    score, reasons, confidence = scorer.score_ml_predictions(predictions, 100.0)
    assert score == pytest.approx(0.8)
    assert confidence == pytest.approx(0.8)
    assert any("increase" in r for r in reasons)


def test_score_ml_predictions_zero_prediction_skipped(scorer):
    predictions = {"lstm": {"prediction": 0.0, "confidence": 80.0}}
    score, reasons, confidence = scorer.score_ml_predictions(predictions, 100.0)
    assert score == 0.0
    assert reasons == []


def test_score_ml_predictions_weighted_mix(scorer):
    predictions = {
        "lstm": {"prediction": 110.0, "confidence": 80.0},
        "xgboost": {"prediction": 90.0, "confidence": 50.0},
    }
    score, _, _ = scorer.score_ml_predictions(predictions, 100.0)
    weighted = 1 * 0.8 * 0.6 + (-1) * 0.5 * 0.4
    assert score == pytest.approx(weighted)


def test_score_ml_predictions_unknown_model_gets_default_weight(scorer):
    predictions = {"custom": {"prediction": 110.0, "confidence": 100.0}}
    score, _, _ = scorer.score_ml_predictions(predictions, 100.0)
    assert score == pytest.approx(1.0)


def test_calculate_combined_score_weighted(scorer):
    scores = {
        AnalysisComponent.TECHNICAL_ANALYSIS: 1.0,
        AnalysisComponent.MARKET_CONTEXT: 0.0,
        AnalysisComponent.EXTERNAL_DATA: 0.0,
        AnalysisComponent.ML_MODELS: 0.0,
    }
    final, reasons = scorer.calculate_combined_score(scores, ["r"], "1d")
    assert final == pytest.approx(40.0)
    assert reasons == ["r"]


def test_calculate_combined_score_zero_weights(scorer):
    scorer.config_manager.get_component_weights.return_value = {}
    scores = {AnalysisComponent.TECHNICAL_ANALYSIS: 1.0}
    final, _ = scorer.calculate_combined_score(scores, [], "1d")
    assert final == 0.0
