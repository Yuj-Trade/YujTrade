from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from domain.types import Candle


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    timeframe: str
    timestamp: datetime
    candles: Sequence[Candle]
    score: float
    confidence: float
    side: str
    entry: float
    stop: float
    target: float
    trend_strength: str = "WEAK"
    volume_surge: float | None = None
    details: Mapping[str, object] = field(default_factory=dict)


def build_snapshot(
    symbol: str,
    timeframe: str,
    candles: Sequence[Candle],
    *,
    score: float,
    confidence: float,
    side: str,
    entry: float,
    stop: float,
    target: float,
    trend_strength: str = "WEAK",
    volume_surge: float | None = None,
    details: Mapping[str, object] | None = None,
) -> MarketSnapshot:
    if not candles:
        raise ValueError("candles must not be empty")
    return MarketSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=candles[-1].timestamp,
        candles=tuple(candles),
        score=score,
        confidence=confidence,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        trend_strength=trend_strength,
        volume_surge=volume_surge,
        details=details or {},
    )
