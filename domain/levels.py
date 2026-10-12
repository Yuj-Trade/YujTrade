import math

from .types import LevelSet, ReasonCode


def validate_levels(side: str, entry: float, stop: float, target: float) -> ReasonCode | None:
    values = (entry, stop, target)
    if any(not math.isfinite(value) or value <= 0 for value in values):
        return ReasonCode.NON_FINITE_PRICE
    normalized = side.lower()
    if normalized == "buy":
        ordered = stop < entry < target
    elif normalized == "sell":
        ordered = target < entry < stop
    else:
        return ReasonCode.INVALID_LEVELS
    return None if ordered else ReasonCode.INVALID_LEVELS


def calculate_levels(
    entry: float,
    volatility: float,
    side: str,
    stop_multiplier: float = 1.5,
    target_multiplier: float = 3.0,
) -> LevelSet:
    if entry <= 0 or volatility < 0:
        raise ValueError("entry and volatility must be non-negative, with entry > 0")
    distance = max(entry * 1e-9, volatility * stop_multiplier)
    reward = max(distance, volatility * target_multiplier)
    normalized_side = side.lower()
    if normalized_side == "buy":
        return LevelSet(entry, entry - distance, entry + reward)
    if normalized_side == "sell":
        return LevelSet(entry, entry + distance, entry - reward)
    raise ValueError(f"Unsupported signal side: {side}")
