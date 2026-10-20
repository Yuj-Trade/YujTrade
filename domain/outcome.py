import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_NO_DATA = "no_data"


@dataclass(frozen=True)
class Outcome:
    success: bool
    exit_price: float
    reason: str


@dataclass(frozen=True)
class Resolution:
    exit_reason: str
    exit_price: float | None
    exit_at: datetime | None
    candles_used: int


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


def resolve_signal_outcome(
    candles: Iterable[Mapping[str, object]],
    side: str,
    entry: float,
    stop: float,
    target: float,
    created_at: datetime,
    expiry_hours: float,
    candle_duration: timedelta,
) -> Resolution:
    normalized_side = side.lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError(f"unsupported side {side!r}")
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    if expiry_hours <= 0:
        raise ValueError("expiry_hours must be positive")
    if candle_duration <= timedelta(0):
        raise ValueError("candle_duration must be positive")

    end_at = created_at + timedelta(hours=expiry_hours)
    window = _window_candles(candles, created_at, end_at)
    if not window:
        return Resolution(_NO_DATA, None, None, 0)
    if window[0][0] > created_at + candle_duration:
        return Resolution(_NO_DATA, None, None, 0)
    if window[-1][0] + candle_duration < end_at:
        return Resolution(_NO_DATA, None, None, 0)

    for index, (timestamp, high, low, _close) in enumerate(window):
        if normalized_side == "buy":
            if low <= stop:
                return Resolution("stop", stop, timestamp, index + 1)
            if high >= target:
                return Resolution("target", target, timestamp, index + 1)
        else:
            if high >= stop:
                return Resolution("stop", stop, timestamp, index + 1)
            if low <= target:
                return Resolution("target", target, timestamp, index + 1)

    for timestamp, _high, _low, close in reversed(window):
        if close is not None:
            return Resolution("expired", close, timestamp, len(window))
    return Resolution(_NO_DATA, None, None, 0)


def _window_candles(
    candles: Iterable[Mapping[str, object]], created_at: datetime, end_at: datetime
) -> list[tuple[datetime, float, float, float | None]]:
    prepared: list[tuple[datetime, float, float, float | None]] = []
    for candle in candles:
        timestamp = _candle_timestamp(candle)
        if timestamp is None or not created_at <= timestamp <= end_at:
            continue
        high = _numeric(candle.get("high"))
        low = _numeric(candle.get("low"))
        if high is None or low is None:
            continue
        prepared.append((timestamp, high, low, _numeric(candle.get("close"))))
    prepared.sort(key=lambda item: item[0])
    return prepared


def _numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number):
        return None
    return number


def _candle_timestamp(candle: Mapping[str, object]) -> datetime | None:
    raw = candle.get("timestamp")
    if raw is None:
        raw = candle.get("time")
    if not isinstance(raw, datetime):
        return None
    if raw.tzinfo is None:
        return raw.replace(tzinfo=UTC)
    return raw.astimezone(UTC)
