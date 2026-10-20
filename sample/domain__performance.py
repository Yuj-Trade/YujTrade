import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

SIDES: frozenset[str] = frozenset({"buy", "sell"})
EXIT_REASONS: frozenset[str] = frozenset({"stop", "target", "expired", "no_data"})


def _require_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")


def _require_positive(value: float, name: str) -> None:
    _require_finite(value, name)
    if value <= 0.0:
        raise ValueError(f"{name} must be positive, got {value}")


def _require_non_negative(value: float, name: str) -> None:
    _require_finite(value, name)
    if value < 0.0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def _require_series(values: Sequence[float], name: str) -> None:
    for value in values:
        _require_finite(value, name)


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
    resolved_at: datetime
    exit_price: float | None
    exit_reason: str
    candles_used: int
    resolver_version: str

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"side must be buy or sell, got {self.side!r}")
        if self.exit_reason not in EXIT_REASONS:
            raise ValueError(f"unknown exit_reason {self.exit_reason!r}")
        _require_positive(self.entry, "entry")
        _require_positive(self.stop, "stop")
        _require_positive(self.target, "target")
        if self.side == "buy" and not self.stop < self.entry:
            raise ValueError("buy signal requires stop below entry")
        if self.side == "sell" and not self.stop > self.entry:
            raise ValueError("sell signal requires stop above entry")
        if self.created_at.tzinfo is None or self.resolved_at.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        if self.resolved_at < self.created_at:
            raise ValueError("resolved_at must not precede created_at")
        if self.candles_used < 0:
            raise ValueError("candles_used must be non-negative")
        if self.exit_reason == "no_data":
            if self.exit_price is not None:
                raise ValueError("no_data resolution must not carry an exit_price")
        elif self.exit_price is None:
            raise ValueError(f"{self.exit_reason} resolution requires an exit_price")
        else:
            _require_positive(self.exit_price, "exit_price")

    def utc_created_at(self) -> datetime:
        return self.created_at.astimezone(UTC)

    def utc_resolved_at(self) -> datetime:
        return self.resolved_at.astimezone(UTC)


def net_r_multiple(record: ResolutionRecord, fee_rate: float, slippage_rate: float) -> float:
    if record.exit_price is None:
        raise ValueError("no_data resolution has no R multiple")
    _require_non_negative(fee_rate, "fee_rate")
    _require_non_negative(slippage_rate, "slippage_rate")
    risk = abs(record.entry - record.stop)
    direction = 1.0 if record.side == "buy" else -1.0
    gross = direction * (record.exit_price - record.entry) / risk
    cost = (fee_rate + slippage_rate) * (record.entry + record.exit_price) / risk
    return gross - cost


def fixed_fraction_return(r_multiple: float, risk_per_trade_pct: float) -> float:
    _require_finite(r_multiple, "r_multiple")
    if not 0.0 < risk_per_trade_pct <= 100.0:
        raise ValueError(f"risk_per_trade_pct must be in (0, 100], got {risk_per_trade_pct}")
    return r_multiple * risk_per_trade_pct / 100.0


def equity_curve(initial_equity: float, fractions: Sequence[float]) -> list[float]:
    _require_positive(initial_equity, "initial_equity")
    equity = initial_equity
    curve = [equity]
    for fraction in fractions:
        _require_finite(fraction, "fraction")
        if fraction <= -1.0:
            raise ValueError("a per-trade fraction of -1 or less would wipe out equity")
        equity *= 1.0 + fraction
        curve.append(equity)
    return curve


@dataclass(frozen=True)
class Drawdown:
    depth: float
    peak_index: int
    trough_index: int

    @property
    def duration(self) -> int:
        return self.trough_index - self.peak_index


def max_drawdown(equity: Sequence[float]) -> Drawdown:
    if not equity:
        raise ValueError("equity series must not be empty")
    best = Drawdown(depth=0.0, peak_index=0, trough_index=0)
    peak = equity[0]
    peak_index = 0
    for index, value in enumerate(equity):
        _require_positive(value, "equity")
        if value > peak:
            peak = value
            peak_index = index
        depth = (peak - value) / peak
        if depth > best.depth:
            best = Drawdown(depth=depth, peak_index=peak_index, trough_index=index)
    return best


def daily_returns(events: Iterable[tuple[date, float]], start: date, end: date) -> list[float]:
    if end < start:
        raise ValueError("end must not precede start")
    grouped: dict[date, float] = {}
    for day, fraction in events:
        _require_finite(fraction, "fraction")
        if fraction <= -1.0:
            raise ValueError("a per-trade fraction of -1 or less would wipe out equity")
        if day < start or day > end:
            raise ValueError(f"event day {day} is outside [{start}, {end}]")
        grouped[day] = grouped.get(day, 1.0) * (1.0 + fraction)
    span = (end - start).days + 1
    return [grouped.get(start + timedelta(days=offset), 1.0) - 1.0 for offset in range(span)]


def sharpe_ratio(
    returns: Sequence[float], risk_free_per_period: float, periods_per_year: float
) -> float | None:
    _require_series(returns, "return")
    _require_finite(risk_free_per_period, "risk_free_per_period")
    _require_positive(periods_per_year, "periods_per_year")
    if len(returns) < 2:
        return None
    excess = [value - risk_free_per_period for value in returns]
    spread = statistics.stdev(excess)
    if spread == 0.0:
        return None
    return statistics.fmean(excess) / spread * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: Sequence[float], minimum_acceptable_per_period: float, periods_per_year: float
) -> float | None:
    _require_series(returns, "return")
    _require_finite(minimum_acceptable_per_period, "minimum_acceptable_per_period")
    _require_positive(periods_per_year, "periods_per_year")
    if len(returns) < 2:
        return None
    shortfalls = [min(value - minimum_acceptable_per_period, 0.0) for value in returns]
    downside = math.sqrt(sum(shortfall * shortfall for shortfall in shortfalls) / len(returns))
    if downside == 0.0:
        return None
    excess_mean = statistics.fmean(returns) - minimum_acceptable_per_period
    return excess_mean / downside * math.sqrt(periods_per_year)


def win_rate(r_values: Sequence[float]) -> float | None:
    _require_series(r_values, "r_value")
    if not r_values:
        return None
    return sum(1 for value in r_values if value > 0.0) / len(r_values)


def profit_factor(r_values: Sequence[float]) -> float | None:
    _require_series(r_values, "r_value")
    gains = sum(value for value in r_values if value > 0.0)
    losses = -sum(value for value in r_values if value < 0.0)
    if losses == 0.0:
        return None
    return gains / losses


def expectancy(r_values: Sequence[float]) -> float | None:
    _require_series(r_values, "r_value")
    if not r_values:
        return None
    return statistics.fmean(r_values)
