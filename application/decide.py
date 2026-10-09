from domain.gates import quality_gate_reason
from domain.types import GateConfig, ReasonCode, Reject, SignalDraft

from .snapshot import MarketSnapshot


def decide(
    snapshot: MarketSnapshot,
    config: GateConfig,
    min_score: float = 0.3,
) -> SignalDraft | Reject:
    if snapshot.score < min_score:
        return Reject(ReasonCode.SCORE_TOO_LOW, {"score": snapshot.score})
    if snapshot.side.lower() not in {"buy", "sell"}:
        return Reject(ReasonCode.DIRECTION_CONFLICT, {"side": snapshot.side})
    reason = quality_gate_reason(
        SignalDraft(
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            side=snapshot.side,
            timestamp=snapshot.timestamp,
            entry=snapshot.entry,
            stop=snapshot.stop,
            target=snapshot.target,
            confidence=snapshot.confidence,
            details=snapshot.details,
        ),
        config,
        snapshot.trend_strength,
        snapshot.volume_surge,
    )
    if reason is not None:
        return Reject(reason, {})
    return SignalDraft(
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        side=snapshot.side,
        timestamp=snapshot.timestamp,
        entry=snapshot.entry,
        stop=snapshot.stop,
        target=snapshot.target,
        confidence=snapshot.confidence,
        details=snapshot.details,
    )
