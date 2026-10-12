from collections.abc import Callable
from typing import Any

from domain.types import GateConfig

_MIN_CONFIDENCE_KEY = "min_confidence_threshold"
_MIN_TREND_KEY = "min_trend_strength"
_MIN_VOLUME_SURGE_KEY = "min_volume_surge"
_TREND_STRENGTHS = {"WEAK", "MODERATE", "STRONG"}


def build_gate_config(get: Callable[[str, Any], Any], timeframe: str) -> GateConfig:
    thresholds = get(_MIN_CONFIDENCE_KEY, {}) or {}
    threshold = thresholds.get(timeframe)
    required = str(get(_MIN_TREND_KEY, "MODERATE")).upper()
    if required not in _TREND_STRENGTHS:
        required = "MODERATE"
    min_surge = get(_MIN_VOLUME_SURGE_KEY, None)
    return GateConfig(
        min_confidence=float(threshold) if threshold is not None else float("-inf"),
        min_trend_strength=required,
        min_volume_surge=float(min_surge) if min_surge is not None else 0.0,
    )
