"""Unit coverage for the domain level calculator and quality gates."""

from datetime import datetime, timezone

import pytest

from domain.gates import passes_quality_gates, quality_gate_reason
from domain.levels import calculate_levels
from domain.types import GateConfig, ReasonCode, SignalDraft


def _draft(confidence: float = 80.0) -> SignalDraft:
    return SignalDraft(
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        timestamp=datetime.now(timezone.utc),
        entry=100.0,
        stop=95.0,
        target=110.0,
        confidence=confidence,
    )


class TestCalculateLevels:
    def test_buy_geometry(self):
        levels = calculate_levels(100.0, 2.0, "buy")
        assert levels.entry == 100.0
        assert levels.stop == pytest.approx(100.0 - 3.0)
        assert levels.target == pytest.approx(100.0 + 6.0)

    def test_sell_geometry(self):
        levels = calculate_levels(100.0, 2.0, "sell")
        assert levels.stop == pytest.approx(103.0)
        assert levels.target == pytest.approx(94.0)

    def test_side_is_case_insensitive(self):
        assert calculate_levels(100.0, 2.0, "BUY").stop < 100.0
        assert calculate_levels(100.0, 2.0, "SELL").stop > 100.0

    def test_invalid_side_rejected(self):
        with pytest.raises(ValueError):
            calculate_levels(100.0, 2.0, "hold")

    def test_non_positive_entry_rejected(self):
        with pytest.raises(ValueError):
            calculate_levels(0.0, 2.0, "buy")

    def test_negative_volatility_rejected(self):
        with pytest.raises(ValueError):
            calculate_levels(100.0, -1.0, "buy")

    def test_zero_volatility_falls_back_to_epsilon_distance(self):
        levels = calculate_levels(100.0, 0.0, "buy")
        assert levels.stop < 100.0
        assert levels.target > 100.0


class TestQualityGates:
    def _config(self) -> GateConfig:
        return GateConfig(min_confidence=70.0, min_trend_strength="MODERATE", min_volume_surge=1.5)

    def test_passes_when_all_thresholds_met(self):
        assert passes_quality_gates(_draft(80.0), self._config(), "STRONG", 2.0) is True

    def test_fails_on_low_confidence(self):
        assert passes_quality_gates(_draft(60.0), self._config(), "STRONG", 2.0) is False

    def test_fails_on_weak_trend(self):
        assert passes_quality_gates(_draft(), self._config(), "WEAK", 2.0) is False

    def test_fails_on_low_surge(self):
        assert passes_quality_gates(_draft(), self._config(), "STRONG", 1.0) is False

    def test_missing_surge_skips_surge_gate(self):
        assert passes_quality_gates(_draft(), self._config(), "STRONG", None) is True

    def test_reason_confidence(self):
        reason = quality_gate_reason(_draft(60.0), self._config(), "STRONG", 2.0)
        assert reason == ReasonCode.CONFIDENCE_TOO_LOW

    def test_reason_trend(self):
        reason = quality_gate_reason(_draft(), self._config(), "WEAK", 2.0)
        assert reason == ReasonCode.TREND_TOO_WEAK

    def test_reason_volume(self):
        reason = quality_gate_reason(_draft(), self._config(), "STRONG", 1.0)
        assert reason == ReasonCode.VOLUME_TOO_LOW

    def test_reason_none_when_clean(self):
        assert quality_gate_reason(_draft(), self._config(), "STRONG", 2.0) is None
