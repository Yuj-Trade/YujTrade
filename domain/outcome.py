from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Outcome:
    success: bool
    exit_price: float
    reason: str


def resolve_outcome(
    candles: Iterable[Mapping[str, float]],
    signal_type: str,
    entry: float,
    stop: float,
    target: float,
    created_at: datetime | None = None,
    expiry_hours: float | None = None,
) -> Outcome | None:
    side = signal_type.lower()
    if side not in {"buy", "sell"}:
        return None
    end_at = (
        created_at + timedelta(hours=expiry_hours)
        if created_at is not None and expiry_hours is not None
        else None
    )
    for candle in candles:
        timestamp = candle.get("timestamp") or candle.get("time")
        if created_at is not None and isinstance(timestamp, datetime) and timestamp < created_at:
            continue
        if end_at is not None and isinstance(timestamp, datetime) and timestamp > end_at:
            break
        high = float(candle["high"])
        low = float(candle["low"])
        if side == "buy":
            if low <= stop:
                return Outcome(False, stop, "stop")
            if high >= target:
                return Outcome(True, target, "target")
        else:
            if high >= stop:
                return Outcome(False, stop, "stop")
            if low <= target:
                return Outcome(True, target, "target")
    return None
