from .types import GateConfig, ReasonCode, SignalDraft


_STRENGTH = {"WEAK": 0, "MODERATE": 1, "STRONG": 2}


def passes_quality_gates(
    signal: SignalDraft,
    config: GateConfig,
    trend_strength: str = "WEAK",
    volume_surge: float | None = None,
) -> bool:
    if signal.confidence < config.min_confidence:
        return False
    if _STRENGTH.get(str(trend_strength).upper(), 0) < _STRENGTH.get(
        str(config.min_trend_strength).upper(), 0
    ):
        return False
    if volume_surge is not None and volume_surge < config.min_volume_surge:
        return False
    return True


def quality_gate_reason(
    signal: SignalDraft,
    config: GateConfig,
    trend_strength: str = "WEAK",
    volume_surge: float | None = None,
) -> ReasonCode | None:
    if signal.confidence < config.min_confidence:
        return ReasonCode.CONFIDENCE_TOO_LOW
    if _STRENGTH.get(str(trend_strength).upper(), 0) < _STRENGTH.get(
        str(config.min_trend_strength).upper(), 0
    ):
        return ReasonCode.TREND_TOO_WEAK
    if volume_surge is not None and volume_surge < config.min_volume_surge:
        return ReasonCode.VOLUME_TOO_LOW
    return None
