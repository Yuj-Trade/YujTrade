import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from domain.performance import (
    ResolutionRecord,
    daily_returns,
    equity_curve,
    expectancy,
    fixed_fraction_return,
    format_utc_timestamp,
    max_drawdown,
    net_r_multiple,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)

REPORT_VERSION = "performance-report-v1"
REPORT_MODE = "paper"
STATUS_OK = "ok"
STATUS_NO_TRADES = "no_trades"
STATUS_INSUFFICIENT_SAMPLE = "insufficient_sample"


@dataclass(frozen=True)
class PerformanceConfig:
    initial_cash: float
    risk_per_trade_pct: float
    fee_rate: float
    slippage_rate: float
    rf_annual: float
    periods_per_year: float
    min_trades_for_ratios: int


@dataclass(frozen=True)
class DrawdownSummary:
    depth: float
    peak_index: int
    trough_index: int
    peak_time: str | None
    trough_time: str | None
    duration_trades: int

    def to_dict(self) -> dict[str, object]:
        return {
            "depth": self.depth,
            "peak_index": self.peak_index,
            "trough_index": self.trough_index,
            "peak_time": self.peak_time,
            "trough_time": self.trough_time,
            "duration_trades": self.duration_trades,
        }


@dataclass(frozen=True)
class PerformanceReport:
    report_version: str
    mode: str
    as_of: str
    period_start: str
    period_end: str
    status: str
    total_resolved: int
    exit_counts: dict[str, int]
    win_rate: float | None
    profit_factor: float | None
    expectancy_r: float | None
    initial_equity: float
    final_equity: float
    total_return: float
    max_drawdown: DrawdownSummary
    sharpe: float | None
    sortino: float | None
    parameters: dict[str, float | int]
    data_hash: str
    config_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "report_version": self.report_version,
            "mode": self.mode,
            "as_of": self.as_of,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "status": self.status,
            "total_resolved": self.total_resolved,
            "exit_counts": dict(self.exit_counts),
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "expectancy_r": self.expectancy_r,
            "initial_equity": self.initial_equity,
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown.to_dict(),
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "parameters": dict(self.parameters),
            "data_hash": self.data_hash,
            "config_hash": self.config_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def build_performance_report(
    records: Sequence[ResolutionRecord], config: PerformanceConfig, as_of: datetime
) -> PerformanceReport:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    as_of_utc = as_of.astimezone(UTC)
    as_of_day = as_of_utc.date()

    ordered = sorted(records, key=_record_sort_key)
    priced = [record for record in ordered if record.exit_at is not None]
    if priced:
        start_day = min(record.exit_at.astimezone(UTC).date() for record in priced)
    else:
        unresolved = [record for record in ordered if record.exit_at is None]
        start_day = min(_record_day(record) for record in unresolved) if unresolved else as_of_day

    included = [record for record in ordered if start_day <= _record_day(record) <= as_of_day]
    included_priced = [record for record in included if record.exit_at is not None]

    r_values = [
        net_r_multiple(record, config.fee_rate, config.slippage_rate) for record in included_priced
    ]
    fractions = [fixed_fraction_return(value, config.risk_per_trade_pct) for value in r_values]
    curve = equity_curve(config.initial_cash, fractions)
    curve_times: list[datetime | None] = [None]
    curve_times.extend(record.exit_at.astimezone(UTC) for record in included_priced)
    drawdown = max_drawdown(curve, curve_times)

    daily = daily_returns(
        [
            (record.exit_at.astimezone(UTC).date(), fraction)
            for record, fraction in zip(included_priced, fractions, strict=True)
        ],
        start_day,
        as_of_day,
    )
    risk_free_per_period = config.rf_annual / config.periods_per_year
    enough = len(included_priced) >= config.min_trades_for_ratios
    sharpe = sharpe_ratio(daily, risk_free_per_period, config.periods_per_year) if enough else None
    sortino = (
        sortino_ratio(daily, risk_free_per_period, config.periods_per_year) if enough else None
    )

    if not included_priced:
        status = STATUS_NO_TRADES
    elif not enough:
        status = STATUS_INSUFFICIENT_SAMPLE
    else:
        status = STATUS_OK

    final_equity = curve[-1]
    total_return = (final_equity / config.initial_cash) - 1.0
    parameters = _parameters(config)

    return PerformanceReport(
        report_version=REPORT_VERSION,
        mode=REPORT_MODE,
        as_of=format_utc_timestamp(as_of_utc),
        period_start=start_day.isoformat(),
        period_end=as_of_day.isoformat(),
        status=status,
        total_resolved=len(included_priced),
        exit_counts=_exit_counts(included),
        win_rate=win_rate(r_values),
        profit_factor=profit_factor(r_values),
        expectancy_r=expectancy(r_values),
        initial_equity=config.initial_cash,
        final_equity=final_equity,
        total_return=total_return,
        max_drawdown=DrawdownSummary(
            depth=drawdown.depth,
            peak_index=drawdown.peak_index,
            trough_index=drawdown.trough_index,
            peak_time=None
            if drawdown.peak_time is None
            else format_utc_timestamp(drawdown.peak_time),
            trough_time=None
            if drawdown.trough_time is None
            else format_utc_timestamp(drawdown.trough_time),
            duration_trades=drawdown.duration,
        ),
        sharpe=sharpe,
        sortino=sortino,
        parameters=parameters,
        data_hash=_data_hash(included),
        config_hash=_config_hash(parameters),
    )


def _record_day(record: ResolutionRecord) -> date:
    if record.exit_at is not None:
        return record.exit_at.astimezone(UTC).date()
    return record.created_at.astimezone(UTC).date()


def _record_sort_key(record: ResolutionRecord) -> tuple[int, str, str]:
    if record.exit_at is None:
        return (1, "", record.signal_id)
    return (0, format_utc_timestamp(record.exit_at), record.signal_id)


def _exit_counts(records: Sequence[ResolutionRecord]) -> dict[str, int]:
    counts = {"stop": 0, "target": 0, "expired": 0, "no_data": 0}
    for record in records:
        counts[record.exit_reason] = counts.get(record.exit_reason, 0) + 1
    return counts


def _parameters(config: PerformanceConfig) -> dict[str, float | int]:
    return {
        "initial_cash": float(config.initial_cash),
        "risk_per_trade_pct": float(config.risk_per_trade_pct),
        "fee_rate": float(config.fee_rate),
        "slippage_rate": float(config.slippage_rate),
        "rf_annual": float(config.rf_annual),
        "periods_per_year": float(config.periods_per_year),
        "min_trades_for_ratios": int(config.min_trades_for_ratios),
    }


def _canonical_record(record: ResolutionRecord) -> dict[str, object]:
    return {
        "signal_id": record.signal_id,
        "symbol": record.symbol,
        "timeframe": record.timeframe,
        "side": record.side,
        "entry": float(record.entry),
        "stop": float(record.stop),
        "target": float(record.target),
        "created_at_utc": format_utc_timestamp(record.created_at),
        "exit_at_utc": None if record.exit_at is None else format_utc_timestamp(record.exit_at),
        "exit_price": None if record.exit_price is None else float(record.exit_price),
        "exit_reason": record.exit_reason,
        "candles_used": int(record.candles_used),
        "resolver_version": record.resolver_version,
    }


def _data_hash(records: Sequence[ResolutionRecord]) -> str:
    payload = [_canonical_record(record) for record in records]
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _config_hash(parameters: dict[str, float | int]) -> str:
    text = json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
