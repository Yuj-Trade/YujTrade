from datetime import UTC, datetime

import pytest

from application.decide import decide
from application.snapshot import build_snapshot
from domain.types import Candle, GateConfig, ReasonCode, Reject, SignalDraft

CANDLE = Candle(datetime(2025, 1, 1, tzinfo=UTC), 100.0, 101.0, 99.0, 100.0, 1.0)
CONFIG = GateConfig(min_confidence=70.0, min_trend_strength="MODERATE", min_volume_surge=1.4)


def _snapshot(**overrides):
    base = dict(
        score=80.0,
        confidence=80.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=112.0,
        trend_strength="STRONG",
        volume_surge=2.0,
    )
    base.update(overrides)
    return build_snapshot("BTC/USDT", "1h", [CANDLE], **base)


def test_valid_snapshot_returns_draft():
    result = decide(_snapshot(), CONFIG, min_score=50.0)
    assert isinstance(result, SignalDraft)


def test_low_confidence_is_rejected():
    result = decide(_snapshot(confidence=60.0), CONFIG, min_score=50.0)
    assert isinstance(result, Reject)
    assert result.reason is ReasonCode.CONFIDENCE_TOO_LOW


def test_weak_trend_is_rejected():
    result = decide(_snapshot(trend_strength="WEAK"), CONFIG, min_score=50.0)
    assert result.reason is ReasonCode.TREND_TOO_WEAK


def test_low_volume_surge_is_rejected():
    result = decide(_snapshot(volume_surge=1.0), CONFIG, min_score=50.0)
    assert result.reason is ReasonCode.VOLUME_TOO_LOW


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"stop": 105.0}, ReasonCode.INVALID_LEVELS),
        ({"target": 90.0}, ReasonCode.INVALID_LEVELS),
        ({"entry": float("nan")}, ReasonCode.NON_FINITE_PRICE),
        ({"target": float("inf")}, ReasonCode.NON_FINITE_PRICE),
    ],
)
def test_invalid_levels_are_rejected_before_quality_gates(overrides, reason):
    result = decide(_snapshot(**overrides), CONFIG, min_score=50.0)
    assert isinstance(result, Reject)
    assert result.reason is reason


def test_score_below_threshold_is_rejected():
    result = decide(_snapshot(score=10.0), CONFIG, min_score=50.0)
    assert result.reason is ReasonCode.SCORE_TOO_LOW
