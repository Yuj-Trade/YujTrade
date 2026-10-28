import dataclasses
from datetime import UTC, datetime

import pytest

from domain.types import (
    Candle,
    GateConfig,
    LevelSet,
    ReasonCode,
    Reject,
    SignalDraft,
)


def test_reason_code_serializes_to_value_string():
    assert ReasonCode.SIZE_ZERO == "size_zero"
    assert ReasonCode.SIZE_ZERO.value == "size_zero"
    assert ReasonCode.INVALID_LEVELS.value == "invalid_levels"


def test_all_reason_codes_are_distinct():
    values = [code.value for code in ReasonCode]
    assert len(values) == len(set(values))


def test_candle_defaults_volume_to_zero():
    candle = Candle(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
    )
    assert candle.volume == 0.0


def test_level_set_is_frozen():
    levels = LevelSet(entry=100.0, stop=95.0, target=110.0)
    assert levels.entry == 100.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        levels.entry = 101.0


def test_gate_config_defaults():
    config = GateConfig()
    assert config.min_confidence == 0.0
    assert config.min_trend_strength == "WEAK"
    assert config.min_volume_surge == 0.0


def test_gate_config_overrides():
    config = GateConfig(min_confidence=70.0, min_trend_strength="STRONG", min_volume_surge=1.5)
    assert config.min_confidence == 70.0
    assert config.min_trend_strength == "STRONG"
    assert config.min_volume_surge == 1.5


def test_signal_draft_details_default_to_empty_mapping():
    draft = SignalDraft(
        symbol="BTC/USDT",
        timeframe="1d",
        side="buy",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        entry=100.0,
        stop=95.0,
        target=110.0,
        confidence=75.0,
    )
    assert dict(draft.details) == {}


def test_reject_details_default_to_empty_mapping():
    reject = Reject(reason=ReasonCode.SCORE_TOO_LOW)
    assert dict(reject.details) == {}


def test_signal_draft_details_accept_mapping():
    draft = SignalDraft(
        symbol="BTC/USDT",
        timeframe="1d",
        side="buy",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        entry=100.0,
        stop=95.0,
        target=110.0,
        confidence=75.0,
        details={"score": 12.5},
    )
    assert draft.details["score"] == 12.5
