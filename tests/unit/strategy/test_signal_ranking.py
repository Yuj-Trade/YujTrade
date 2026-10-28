from types import SimpleNamespace

import pytest

from common.core import MacroEconomicData, SignalType
from strategy.signal_ranking import SignalRanking


def make_signal(
    confidence: float = 80.0,
    rr: float = 4.0,
    timeframe: str = "1d",
    ml: float | None = None,
    signal_type: SignalType = SignalType.BUY,
    macro: MacroEconomicData | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        confidence_score=confidence,
        risk_reward_ratio=rr,
        timeframe=timeframe,
        ml_confidence=ml,
        signal_type=signal_type,
        macro_data=macro,
    )


def test_plain_score_uses_timeframe_and_rr_multipliers():
    signal = make_signal(confidence=100.0, rr=5.0, timeframe="1d")
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(300.0)


def test_very_high_rr_is_capped_at_five():
    signal = make_signal(confidence=100.0, rr=50.0, timeframe="1d")
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(300.0)


def test_zero_rr_uses_neutral_multiplier():
    signal = make_signal(confidence=100.0, rr=0.0, timeframe="1d")
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(60.0)


def test_negative_rr_uses_neutral_multiplier():
    signal = make_signal(confidence=100.0, rr=-2.0, timeframe="1d")
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(60.0)


def test_unknown_timeframe_has_unit_weight():
    signal = make_signal(confidence=100.0, rr=5.0, timeframe="15m")
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(250.0)


def test_monthly_timeframe_has_top_weight():
    signal = make_signal(confidence=100.0, rr=5.0, timeframe="1M")
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(500.0)


def test_ml_confidence_above_one_is_scaled():
    signal = make_signal(confidence=100.0, rr=5.0, timeframe="1d", ml=80.0)
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(309.0)


def test_ml_confidence_fraction_is_used_as_is():
    signal = make_signal(confidence=100.0, rr=5.0, timeframe="1d", ml=0.8)
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(309.0)


def test_ml_confidence_zero_gives_minimum_multiplier():
    signal = make_signal(confidence=100.0, rr=5.0, timeframe="1d", ml=0.0)
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(285.0)


@pytest.mark.parametrize("ml", ["abc", object(), []])
def test_unparsable_ml_confidence_is_ignored(ml):
    signal = make_signal(confidence=100.0, rr=5.0, timeframe="1d", ml=ml)
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(300.0)


def test_high_fed_rate_penalizes_buy():
    signal = make_signal(macro=MacroEconomicData(fed_rate=4.5))
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(153.6)


def test_high_fed_rate_does_not_penalize_sell():
    signal = make_signal(rr=0.0, signal_type=SignalType.SELL, macro=MacroEconomicData(fed_rate=4.5))
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(48.0)


def test_low_fed_rate_penalizes_sell():
    signal = make_signal(rr=0.0, signal_type=SignalType.SELL, macro=MacroEconomicData(fed_rate=1.5))
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(38.4)


def test_neutral_fed_rate_no_penalty():
    signal = make_signal(macro=MacroEconomicData(fed_rate=3.0))
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(192.0)


def test_missing_fed_rate_no_penalty():
    signal = make_signal(macro=MacroEconomicData(cpi=3.0))
    assert SignalRanking.calculate_signal_score(signal) == pytest.approx(192.0)


def test_no_macro_no_penalty():
    assert SignalRanking.calculate_signal_score(make_signal()) == pytest.approx(192.0)


def test_rank_signals_orders_descending_by_score():
    low = make_signal(confidence=50.0, rr=1.0, timeframe="1h")
    mid = make_signal(confidence=80.0, rr=4.0, timeframe="1d")
    high = make_signal(confidence=100.0, rr=5.0, timeframe="1M")
    ranked = SignalRanking.rank_signals([low, high, mid])
    assert ranked == [high, mid, low]


def test_rank_signals_on_empty_list():
    assert SignalRanking.rank_signals([]) == []
