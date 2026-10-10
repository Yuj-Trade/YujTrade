from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ReasonCode(str, Enum):
    SCORE_TOO_LOW = "score_too_low"
    DIRECTION_CONFLICT = "direction_conflict"
    CONFIDENCE_TOO_LOW = "confidence_too_low"
    TREND_TOO_WEAK = "trend_too_weak"
    VOLUME_TOO_LOW = "volume_too_low"
    SIZE_ZERO = "size_zero"
    MTF_DATA_MISSING = "mtf_data_missing"


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class LevelSet:
    entry: float
    stop: float
    target: float


@dataclass(frozen=True)
class GateConfig:
    min_confidence: float = 0.0
    min_trend_strength: str = "WEAK"
    min_volume_surge: float = 0.0


@dataclass(frozen=True)
class SignalDraft:
    symbol: str
    timeframe: str
    side: str
    timestamp: datetime
    entry: float
    stop: float
    target: float
    confidence: float
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Reject:
    reason: ReasonCode
    details: Mapping[str, object] = field(default_factory=dict)
