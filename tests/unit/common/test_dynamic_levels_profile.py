import numpy as np
import pandas as pd
import pytest

from common.core import MarketAnalysis, MarketCondition, SignalType, TrendDirection, TrendStrength
from common.utils import calculate_dynamic_levels

ADX_GRID = [10.0, 25.0, 35.0, 35.0001, 39.9999, 40.0, 40.0001, 55.0, 80.0]

SUPPORTS = (95.0, 98.0, 101.0)
RESISTANCES = (103.0, 105.0, 140.0)

LAST_CLOSE = 101.0
VOLATILITY = 2.0


def _frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=60, freq="1h", tz="UTC")
    closes = np.linspace(100.0, LAST_CLOSE, 60)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": np.linspace(10, 20, 60),
        },
        index=index,
    )


def _context(adx: float) -> MarketAnalysis:
    return MarketAnalysis(
        trend=TrendDirection.BULLISH,
        trend_strength=TrendStrength.STRONG,
        volatility=2.0,
        volume_trend="RISING",
        support_levels=list(SUPPORTS),
        resistance_levels=list(RESISTANCES),
        momentum_score=0.5,
        market_condition=MarketCondition.NEUTRAL,
        trend_acceleration=0.1,
        volume_confirmation=True,
        volume_ratio=1.6,
        adx=adx,
    )


def _expected(data, signal_type, adx, stop_structure, target_structure):
    volatility_multiplier = 1.0 + np.clip(VOLATILITY / 10, 0, 1)
    atr = (VOLATILITY / 100 * LAST_CLOSE) * volatility_multiplier
    min_rr = 2.0 if adx > 35 else 1.8
    entry = float(LAST_CLOSE)
    risk = atr * (1.5 if adx > 40 else 1.2)
    if signal_type == SignalType.BUY:
        base_stop = entry - risk
        base_target = entry + (risk * min_rr)
    else:
        base_stop = entry + risk
        base_target = entry - (risk * min_rr)
    if signal_type == SignalType.BUY:
        stop_levels = [s for s in SUPPORTS if s < entry and s > base_stop - risk]
        target_levels = [r for r in RESISTANCES if r > entry and r < base_target + risk]
        stop = max(stop_levels) if stop_levels else base_stop
        target = min(target_levels) if target_levels else base_target
    else:
        stop_levels = [r for r in RESISTANCES if r > entry and r < base_stop + risk]
        target_levels = [s for s in SUPPORTS if s < entry and s > base_target - risk]
        stop = min(stop_levels) if stop_levels else base_stop
        target = max(target_levels) if target_levels else base_target
    if not stop_structure:
        stop = base_stop
    if not target_structure:
        target = base_target
    return {"tight_stop": stop, "primary_exit": target}


@pytest.mark.parametrize("signal_type", [SignalType.BUY, SignalType.SELL])
@pytest.mark.parametrize("stop_structure", [True, False])
@pytest.mark.parametrize("target_structure", [True, False])
def test_default_parameters_match_the_old_literals(signal_type, stop_structure, target_structure):
    data = _frame()
    context = _context(45.0)
    for adx in ADX_GRID:
        context = _context(adx)
        levels = calculate_dynamic_levels(
            data,
            signal_type,
            context,
            stop_use_structure_levels=stop_structure,
            target_use_structure_levels=target_structure,
        )
        expected = _expected(data, signal_type, adx, stop_structure, target_structure)
        assert levels["tight_stop"] == pytest.approx(expected["tight_stop"]), adx
        assert levels["primary_exit"] == pytest.approx(expected["primary_exit"]), adx


@pytest.mark.parametrize("adx", ADX_GRID)
def test_defaults_reproduce_legacy_values_when_no_arguments_are_passed(adx):
    data = _frame()
    context = _context(adx)
    plain = calculate_dynamic_levels(data, SignalType.BUY, context)
    expected = _expected(data, SignalType.BUY, adx, True, True)
    assert plain["tight_stop"] == pytest.approx(expected["tight_stop"])
    assert plain["primary_exit"] == pytest.approx(expected["primary_exit"])


def test_profile_overrides_change_the_stop_and_target():
    data = _frame()
    context = _context(42.0)
    legacy = calculate_dynamic_levels(data, SignalType.BUY, context)
    changed = calculate_dynamic_levels(
        data,
        SignalType.BUY,
        context,
        stop_atr_multiplier_base=2.0,
        stop_atr_multiplier_high_adx=2.0,
        target_min_rr_base=3.0,
        target_min_rr_high_adx=3.0,
        target_adx_threshold=0.0,
        stop_use_structure_levels=False,
        target_use_structure_levels=False,
    )
    assert changed["tight_stop"] < legacy["tight_stop"]
    assert changed["primary_exit"] > legacy["primary_exit"]


def test_structure_flags_only_affect_their_own_level():
    data = _frame()
    context = _context(42.0)
    stop_only = calculate_dynamic_levels(
        data, SignalType.BUY, context, stop_use_structure_levels=False
    )
    target_only = calculate_dynamic_levels(
        data, SignalType.BUY, context, target_use_structure_levels=False
    )
    both = calculate_dynamic_levels(
        data,
        SignalType.BUY,
        context,
        stop_use_structure_levels=False,
        target_use_structure_levels=False,
    )
    assert (
        stop_only["primary_exit"]
        == calculate_dynamic_levels(data, SignalType.BUY, context)["primary_exit"]
    )
    assert (
        target_only["tight_stop"]
        == calculate_dynamic_levels(data, SignalType.BUY, context)["tight_stop"]
    )
    assert both["tight_stop"] == stop_only["tight_stop"]
    assert both["primary_exit"] == target_only["primary_exit"]
