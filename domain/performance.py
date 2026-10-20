import math
from dataclasses import dataclass
from datetime import UTC, datetime

SIDES: frozenset[str] = frozenset({"buy", "sell"})
EXIT_REASONS: frozenset[str] = frozenset({"stop", "target", "expired", "no_data"})
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"
RESOLVER_VERSION = "paper-resolution-v1"


def format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _require_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")


def _require_positive(value: float, name: str) -> None:
    _require_finite(value, name)
    if value <= 0.0:
        raise ValueError(f"{name} must be positive, got {value}")


@dataclass(frozen=True)
class ResolutionRecord:
    signal_id: str
    symbol: str
    timeframe: str
    side: str
    entry: float
    stop: float
    target: float
    created_at: datetime
    exit_at: datetime | None
    exit_price: float | None
    exit_reason: str
    candles_used: int
    resolver_version: str

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"side must be buy or sell, got {self.side!r}")
        if self.exit_reason not in EXIT_REASONS:
            raise ValueError(f"unknown exit_reason {self.exit_reason!r}")
        if not self.signal_id:
            raise ValueError("signal_id must not be empty")
        _require_positive(self.entry, "entry")
        _require_positive(self.stop, "stop")
        _require_positive(self.target, "target")
        if self.side == "buy" and not self.stop < self.entry:
            raise ValueError("buy signal requires stop below entry")
        if self.side == "sell" and not self.stop > self.entry:
            raise ValueError("sell signal requires stop above entry")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.candles_used < 0:
            raise ValueError("candles_used must be non-negative")
        if self.exit_reason == "no_data":
            if self.exit_price is not None:
                raise ValueError("no_data resolution must not carry an exit_price")
            if self.exit_at is not None:
                raise ValueError("no_data resolution must not carry an exit_at")
        else:
            if self.exit_price is None:
                raise ValueError(f"{self.exit_reason} resolution requires an exit_price")
            _require_positive(self.exit_price, "exit_price")
            if self.exit_at is None:
                raise ValueError(f"{self.exit_reason} resolution requires an exit_at")
            if self.exit_at.tzinfo is None:
                raise ValueError("exit_at must be timezone-aware")
            if self.exit_at < self.created_at:
                raise ValueError("exit_at must not precede created_at")

    def utc_created_at(self) -> datetime:
        return self.created_at.astimezone(UTC)

    def utc_exit_at(self) -> datetime | None:
        if self.exit_at is None:
            return None
        return self.exit_at.astimezone(UTC)
