import math

from application.gate_config import build_gate_config
from domain.types import GateConfig


def _get(values):
    def get(key, default=None):
        return values.get(key, default)

    return get


def test_threshold_is_read_per_timeframe():
    get = _get({"min_confidence_threshold": {"1h": 82, "1d": 72}})
    assert build_gate_config(get, "1d").min_confidence == 72.0


def test_missing_timeframe_threshold_is_negative_infinity():
    get = _get({"min_confidence_threshold": {"1h": 82}})
    assert build_gate_config(get, "4h").min_confidence == -math.inf


def test_trend_strength_is_normalized_and_falls_back():
    assert build_gate_config(_get({"min_trend_strength": "strong"}), "1h").min_trend_strength == (
        "STRONG"
    )
    assert build_gate_config(_get({"min_trend_strength": "bogus"}), "1h").min_trend_strength == (
        "MODERATE"
    )


def test_volume_surge_defaults_to_zero_when_absent():
    assert build_gate_config(_get({}), "1h").min_volume_surge == 0.0


def test_returns_gate_config_instance():
    assert isinstance(build_gate_config(_get({}), "1h"), GateConfig)
