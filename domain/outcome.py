import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from domain.costs import first_candle_quote_volume

_NO_DATA = "no_data"
EVENT_KINDS: frozenset[str] = frozenset({"target", "stop", "expired"})


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
    entry_quote_volume: float | None = None


@dataclass(frozen=True)
class OutcomeEvent:
    signal_id: str
    kind: str
    price: float
    at: datetime

    def __post_init__(self) -> None:
        if not self.signal_id:
            raise ValueError("signal_id must be non-empty")
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unsupported outcome kind {self.kind!r}")
        if not math.isfinite(self.price) or self.price <= 0:
            raise ValueError("price must be a positive finite number")
        if self.at.tzinfo is None:
            raise ValueError("at must be timezone-aware")


def event_from_resolution(signal_id: str, resolution: Resolution) -> OutcomeEvent | None:
    if (
        resolution.exit_reason not in EVENT_KINDS
        or resolution.exit_price is None
        or resolution.exit_at is None
    ):
        return None
    return OutcomeEvent(
        signal_id, resolution.exit_reason, resolution.exit_price, resolution.exit_at
    )


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
    entry_volume = first_candle_quote_volume(candles, created_at)
    window = _window_candles(candles, created_at, end_at)
    if not window:
        return Resolution(_NO_DATA, None, None, 0, entry_volume)
    if window[0][0] > created_at + candle_duration:
        return Resolution(_NO_DATA, None, None, 0, entry_volume)
    if window[-1][0] + candle_duration < end_at:
        return Resolution(_NO_DATA, None, None, 0, entry_volume)

    hit = _first_barrier_hit(window, normalized_side, stop, target)
    if hit is not None:
        return Resolution(
            hit.exit_reason, hit.exit_price, hit.exit_at, hit.candles_used, entry_volume
        )

    for timestamp, _high, _low, close in reversed(window):
        if close is not None:
            return Resolution("expired", close, timestamp, len(window), entry_volume)
    return Resolution(_NO_DATA, None, None, 0, entry_volume)


def _first_barrier_hit(
    window: Sequence[tuple[datetime, float, float, float | None]],
    side: str,
    stop: float,
    target: float,
) -> Resolution | None:
    for index, (timestamp, high, low, _close) in enumerate(window):
        if side == "buy":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target
        if stop_hit:
            return Resolution("stop", stop, timestamp, index + 1)
        if target_hit:
            return Resolution("target", target, timestamp, index + 1)
    return None


def observe_signal_barrier(
    candles: Iterable[Mapping[str, object]],
    side: str,
    stop: float,
    target: float,
    created_at: datetime,
    observed_until: datetime,
    candle_duration: timedelta,
) -> Resolution | None:
    normalized_side = side.lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError(f"unsupported side {side!r}")
    if created_at.tzinfo is None or observed_until.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    if candle_duration <= timedelta(0):
        raise ValueError("candle_duration must be positive")
    closed = [
        item
        for item in _window_candles(candles, created_at, observed_until)
        if item[0] + candle_duration <= observed_until
    ]
    if not closed or closed[0][0] > created_at + candle_duration:
        return None
    return _first_barrier_hit(closed, normalized_side, stop, target)


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
