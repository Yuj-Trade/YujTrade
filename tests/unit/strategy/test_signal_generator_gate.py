from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from application.decide import decide
from application.gate_config import build_gate_config
from application.snapshot import build_snapshot
from common.core import MarketAnalysis, MarketCondition, TrendDirection, TrendStrength
from config.settings import ConfigManager
from domain.gates import quality_gate_reason
from domain.types import Candle, GateConfig, Reject, SignalDraft
from strategy.signal_generator import SignalGenerator


def _weak_analysis() -> MarketAnalysis:
    return MarketAnalysis(
        trend=TrendDirection.SIDEWAYS,
        trend_strength=TrendStrength.WEAK,
        volatility=1.5,
        volume_trend="stable",
        support_levels=[49000],
        resistance_levels=[51000],
        momentum_score=0.0,
        market_condition=MarketCondition.NEUTRAL,
        trend_acceleration=0.0,
        volume_confirmation=False,
        hurst_exponent=0.5,
        volume_trend_score=0.0,
        volume_ratio=1.0,
        adx=15.0,
        candle_patterns=[],
    )


def _generator() -> SignalGenerator:
    provider = MagicMock()
    for name in (
        "get_derivatives_data",
        "get_fundamental_data",
        "get_onchain_data",
        "get_order_book",
        "get_macro_data",
        "get_trending_data",
        "get_all_indices",
    ):
        setattr(provider, name, AsyncMock(return_value=None))
    model_manager = MagicMock()
    model_manager.predict_with_confidence = AsyncMock(return_value=None)
    return SignalGenerator(provider, model_manager, ConfigManager())


def _get(values):
    def get(key, default=None):
        return values.get(key, default)

    return get


def test_same_config_gives_same_accept_decision_in_service_and_generator_paths():
    values = {
        "min_confidence_threshold": {"1h": 82},
        "min_trend_strength": "MODERATE",
        "min_volume_surge": 1.4,
    }
    config = build_gate_config(_get(values), "1h")
    assert isinstance(config, GateConfig)
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    draft = SignalDraft(
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        timestamp=stamp,
        entry=100.0,
        stop=95.0,
        target=112.0,
        confidence=90.0,
    )
    service_reason = quality_gate_reason(draft, config, "STRONG", 2.0)
    snapshot = build_snapshot(
        "BTC/USDT",
        "1h",
        [Candle(stamp, 100.0, 101.0, 99.0, 100.0, 1.0)],
        score=90.0,
        confidence=90.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=112.0,
        trend_strength="STRONG",
        volume_surge=2.0,
    )
    decision = decide(snapshot, config, min_score=10.0)
    assert service_reason is None
    assert not isinstance(decision, Reject)


def test_same_config_gives_same_reject_decision_in_both_paths():
    values = {
        "min_confidence_threshold": {"1h": 82},
        "min_trend_strength": "MODERATE",
        "min_volume_surge": 1.4,
    }
    config = build_gate_config(_get(values), "1h")
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    draft = SignalDraft(
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        timestamp=stamp,
        entry=100.0,
        stop=95.0,
        target=112.0,
        confidence=90.0,
    )
    service_reason = quality_gate_reason(draft, config, "WEAK", 2.0)
    snapshot = build_snapshot(
        "BTC/USDT",
        "1h",
        [Candle(stamp, 100.0, 101.0, 99.0, 100.0, 1.0)],
        score=90.0,
        confidence=90.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=112.0,
        trend_strength="WEAK",
        volume_surge=2.0,
    )
    decision = decide(snapshot, config, min_score=10.0)
    assert service_reason is not None
    assert isinstance(decision, Reject)
    assert decision.reason is service_reason


def test_generator_builds_gate_from_config_manager():
    generator = _generator()
    config = build_gate_config(generator.config_manager.get, "1h")
    assert isinstance(config, GateConfig)
    assert config.min_trend_strength == "MODERATE"


@pytest.mark.asyncio
async def test_weak_trend_signal_is_dropped_not_returned(valid_1h_ohlcv: pd.DataFrame):
    generator = _generator()
    generator.market_analyzer.analyze_market_condition = MagicMock(return_value=_weak_analysis())
    generator.scorer.calculate_combined_score = MagicMock(return_value=(90.0, ["r"]))
    result = await generator.generate_signal(
        "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
    )
    assert result is None
