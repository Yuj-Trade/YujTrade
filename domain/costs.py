import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

LIQUIDITY_LABELS: frozenset[str] = frozenset({"maker", "taker"})
EXIT_REASONS: frozenset[str] = frozenset({"target", "stop", "expired"})
LEGACY_REPORT_VERSION = "legacy-report-v1"
LEGACY_SIMULATOR_VERSION = "legacy-simulator-v1"

_FIELDS = (
    "version",
    "maker_fee_rate",
    "taker_fee_rate",
    "entry_liquidity",
    "target_exit_liquidity",
    "stop_exit_liquidity",
    "expiry_exit_liquidity",
    "entry_slippage_rate",
    "market_exit_slippage_rate",
    "target_exit_slippage_rate",
    "funding_rate_per_period",
    "funding_period_hours",
    "max_volume_participation",
)
_LIQUIDITY_FIELDS = (
    "entry_liquidity",
    "target_exit_liquidity",
    "stop_exit_liquidity",
    "expiry_exit_liquidity",
)
_RATE_FIELDS = (
    "maker_fee_rate",
    "taker_fee_rate",
    "entry_slippage_rate",
    "market_exit_slippage_rate",
    "target_exit_slippage_rate",
    "funding_rate_per_period",
)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value}")
    return number


@dataclass(frozen=True)
class CostProfile:
    version: str
    maker_fee_rate: float
    taker_fee_rate: float
    entry_liquidity: str
    target_exit_liquidity: str
    stop_exit_liquidity: str
    expiry_exit_liquidity: str
    entry_slippage_rate: float
    market_exit_slippage_rate: float
    target_exit_slippage_rate: float
    funding_rate_per_period: float
    funding_period_hours: float
    max_volume_participation: float

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("version must be a non-empty string")
        for name in _LIQUIDITY_FIELDS:
            label = getattr(self, name)
            if label not in LIQUIDITY_LABELS:
                raise ValueError(f"{name} must be maker or taker, got {label!r}")
        for name in _RATE_FIELDS:
            if _finite(getattr(self, name), name) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if _finite(self.funding_period_hours, "funding_period_hours") <= 0.0:
            raise ValueError("funding_period_hours must be positive")
        participation = _finite(self.max_volume_participation, "max_volume_participation")
        if not 0.0 < participation <= 1.0:
            raise ValueError("max_volume_participation must lie in (0, 1]")

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "CostProfile":
        given = set(mapping)
        unknown = sorted(given.difference(_FIELDS))
        if unknown:
            raise ValueError(f"unknown cost profile keys: {unknown}")
        missing = [name for name in _FIELDS if name not in given]
        if missing:
            raise ValueError(f"missing cost profile keys: {missing}")
        return cls(**{name: mapping[name] for name in _FIELDS})


def cost_profile_from_config(
    raw: Mapping[str, Any] | None, defaults: Mapping[str, Any]
) -> CostProfile:
    merged: dict[str, Any] = {**dict(defaults), **dict(raw or {})}
    return CostProfile.from_mapping(merged)


def legacy_report_profile(fee_rate: float, slippage_rate: float) -> CostProfile:
    fee = _finite(fee_rate, "fee_rate")
    slippage = _finite(slippage_rate, "slippage_rate")
    return CostProfile(
        version=LEGACY_REPORT_VERSION,
        maker_fee_rate=fee,
        taker_fee_rate=fee,
        entry_liquidity="taker",
        target_exit_liquidity="taker",
        stop_exit_liquidity="taker",
        expiry_exit_liquidity="taker",
        entry_slippage_rate=slippage,
        market_exit_slippage_rate=slippage,
        target_exit_slippage_rate=slippage,
        funding_rate_per_period=0.0,
        funding_period_hours=8.0,
        max_volume_participation=1.0,
    )


def legacy_simulator_profile(commission_rate: float, slippage_rate: float) -> CostProfile:
    commission = _finite(commission_rate, "commission_rate")
    slippage = _finite(slippage_rate, "slippage_rate")
    return CostProfile(
        version=LEGACY_SIMULATOR_VERSION,
        maker_fee_rate=commission,
        taker_fee_rate=commission,
        entry_liquidity="taker",
        target_exit_liquidity="taker",
        stop_exit_liquidity="taker",
        expiry_exit_liquidity="taker",
        entry_slippage_rate=slippage,
        market_exit_slippage_rate=slippage,
        target_exit_slippage_rate=slippage,
        funding_rate_per_period=0.0,
        funding_period_hours=8.0,
        max_volume_participation=1.0,
    )


def fee_rate(profile: CostProfile, liquidity: str) -> float:
    if liquidity == "maker":
        return profile.maker_fee_rate
    if liquidity == "taker":
        return profile.taker_fee_rate
    raise ValueError(f"unknown liquidity label {liquidity!r}")


def _exit_liquidity(profile: CostProfile, exit_reason: str) -> str:
    if exit_reason == "target":
        return profile.target_exit_liquidity
    if exit_reason == "stop":
        return profile.stop_exit_liquidity
    if exit_reason == "expired":
        return profile.expiry_exit_liquidity
    raise ValueError(f"unsupported exit reason {exit_reason!r}")


def cost_per_unit(
    entry: float,
    exit_price: float,
    exit_reason: str,
    holding_hours: float,
    profile: CostProfile,
) -> float:
    entry = _finite(entry, "entry")
    exit_price = _finite(exit_price, "exit_price")
    holding = _finite(holding_hours, "holding_hours")
    if holding < 0.0:
        raise ValueError("holding_hours must be non-negative")
    liquidity_x = _exit_liquidity(profile, exit_reason)

    fee_e = fee_rate(profile, profile.entry_liquidity)
    slip_e = profile.entry_slippage_rate if profile.entry_liquidity == "taker" else 0.0

    fee_x = fee_rate(profile, liquidity_x)
    if liquidity_x == "taker":
        slip_x = (
            profile.target_exit_slippage_rate
            if exit_reason == "target"
            else profile.market_exit_slippage_rate
        )
    else:
        slip_x = 0.0

    funding_unit = (
        profile.funding_rate_per_period * (holding / profile.funding_period_hours) * entry
    )
    return (fee_e + slip_e) * entry + (fee_x + slip_x) * exit_price + funding_unit


def net_r(
    entry: float,
    stop: float,
    exit_price: float,
    side: str,
    exit_reason: str,
    holding_hours: float,
    profile: CostProfile,
    fill_ratio: float = 1.0,
) -> float:
    entry = _finite(entry, "entry")
    stop = _finite(stop, "stop")
    exit_price = _finite(exit_price, "exit_price")
    fill = _finite(fill_ratio, "fill_ratio")
    if not 0.0 < fill <= 1.0:
        raise ValueError("fill_ratio must lie in (0, 1]")
    if side not in ("buy", "sell"):
        raise ValueError(f"unsupported side {side!r}")
    risk = abs(entry - stop)
    if risk == 0.0:
        raise ValueError("entry and stop must differ")
    direction = 1.0 if side == "buy" else -1.0
    gross_unit = direction * (exit_price - entry)
    cost_unit = cost_per_unit(entry, exit_price, exit_reason, holding_hours, profile)
    return fill * (gross_unit - cost_unit) / risk


def fill_fraction(notional: float, quote_volume: float, max_volume_participation: float) -> float:
    notional = _finite(notional, "notional")
    volume = _finite(quote_volume, "quote_volume")
    participation = _finite(max_volume_participation, "max_volume_participation")
    if notional <= 0.0:
        raise ValueError("notional must be positive")
    if volume < 0.0:
        raise ValueError("quote_volume must be non-negative")
    if not 0.0 < participation <= 1.0:
        raise ValueError("max_volume_participation must lie in (0, 1]")
    return min(1.0, participation * volume / notional)


def first_candle_quote_volume(
    candles: Iterable[Mapping[str, object]], not_before: datetime
) -> float | None:
    if not_before.tzinfo is None:
        raise ValueError("not_before must be timezone-aware")
    best: tuple[datetime, Mapping[str, object]] | None = None
    for candle in candles:
        moment = _candle_time(candle)
        if moment is None or moment < not_before:
            continue
        if best is None or moment < best[0]:
            best = (moment, candle)
    if best is None:
        return None
    return _quote_volume(best[1])


def _candle_time(candle: Mapping[str, object]) -> datetime | None:
    raw = candle.get("timestamp")
    if raw is None:
        raw = candle.get("time")
    if not isinstance(raw, datetime):
        return None
    return raw


def _quote_volume(candle: Mapping[str, object]) -> float | None:
    volume = _numeric(candle.get("volume"))
    close = _numeric(candle.get("close"))
    if volume is None or close is None or volume < 0.0 or close <= 0.0:
        return None
    return volume * close


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
