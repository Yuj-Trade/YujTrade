import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from domain.costs import (
    CostProfile,
    fill_fraction,
    legacy_report_profile,
)
from domain.performance import (
    ResolutionRecord,
    daily_returns,
    equity_curve,
    expectancy,
    fixed_fraction_return,
    format_utc_timestamp,
    max_drawdown,
    net_r_for_profile,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)

REPORT_VERSION = "performance-report-v2"
REPORT_MODE = "paper"
STATUS_OK = "ok"
STATUS_NO_TRADES = "no_trades"
STATUS_INSUFFICIENT_SAMPLE = "insufficient_sample"
LEGACY_RESOLUTIONS_NOTE = (
    "resolutions recorded before the phase-3 resolver are excluded and are not backfilled"
)


@dataclass(frozen=True)
class PerformanceConfig:
    initial_cash: float
    risk_per_trade_pct: float
    fee_rate: float
    slippage_rate: float
    rf_annual: float
    periods_per_year: float
    min_trades_for_ratios: int
    cost_profile: CostProfile | None = None

    def effective_profile(self) -> CostProfile:
        if self.cost_profile is not None:
            return self.cost_profile
        return legacy_report_profile(self.fee_rate, self.slippage_rate)


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
    parameters: dict[str, float | int | str]
    data_hash: str
    config_hash: str
    equity_source: str = "signal_model"
    coverage: dict[str, int | bool] | None = None
    legacy_resolutions_note: str = LEGACY_RESOLUTIONS_NOTE

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
            "equity_source": self.equity_source,
            "coverage": dict(self.coverage or {}),
            "legacy_resolutions_note": self.legacy_resolutions_note,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class _PricedEntry:
    record: ResolutionRecord
    fill_ratio: float
    r_value: float


def build_performance_report(
    records: Sequence[ResolutionRecord], config: PerformanceConfig, as_of: datetime
) -> PerformanceReport:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    as_of_utc = as_of.astimezone(UTC)
    as_of_day = as_of_utc.date()
    profile = config.effective_profile()

    ordered = sorted(records, key=_record_sort_key)
    priced = [record for record in ordered if record.exit_at is not None]
    if priced:
        start_day = min(record.exit_at.astimezone(UTC).date() for record in priced)
    else:
        unresolved = [record for record in ordered if record.exit_at is None]
        start_day = min(_record_day(record) for record in unresolved) if unresolved else as_of_day

    included = [record for record in ordered if start_day <= _record_day(record) <= as_of_day]
    included_priced = [record for record in included if record.exit_at is not None]

    reference_risk = config.initial_cash * config.risk_per_trade_pct / 100.0
    entries: list[_PricedEntry] = []
    unfilled = 0
    legacy_full_fill = 0
    for record in included_priced:
        if record.entry_quote_volume is None:
            ratio = 1.0
            legacy_full_fill += 1
        else:
            risk = abs(record.entry - record.stop)
            notional = reference_risk * record.entry / risk
            ratio = fill_fraction(
                notional, record.entry_quote_volume, profile.max_volume_participation
            )
        if ratio == 0.0:
            unfilled += 1
            continue
        exit_at = record.exit_at
        assert exit_at is not None
        holding = max(0.0, (exit_at - record.created_at).total_seconds() / 3600.0)
        value = net_r_for_profile(record, profile, ratio, holding)
        entries.append(_PricedEntry(record, ratio, value))

    r_values = [entry.r_value for entry in entries]
    fractions = [fixed_fraction_return(value, config.risk_per_trade_pct) for value in r_values]
    curve = equity_curve(config.initial_cash, fractions)
    curve_times: list[datetime | None] = [None]
    curve_times.extend(entry.record.exit_at.astimezone(UTC) for entry in entries)
    drawdown = max_drawdown(curve, curve_times)

    daily = daily_returns(
        [
            (entry.record.exit_at.astimezone(UTC).date(), fraction)
            for entry, fraction in zip(entries, fractions, strict=True)
        ],
        start_day,
        as_of_day,
    )
    risk_free_per_period = config.rf_annual / config.periods_per_year
    enough = len(entries) >= config.min_trades_for_ratios
    sharpe = sharpe_ratio(daily, risk_free_per_period, config.periods_per_year) if enough else None
    sortino = (
        sortino_ratio(daily, risk_free_per_period, config.periods_per_year) if enough else None
    )

    if not entries:
        status = STATUS_NO_TRADES
    elif not enough:
        status = STATUS_INSUFFICIENT_SAMPLE
    else:
        status = STATUS_OK

    final_equity = curve[-1]
    total_return = (final_equity / config.initial_cash) - 1.0
    parameters = _parameters(config, profile)

    return PerformanceReport(
        report_version=REPORT_VERSION,
        mode=REPORT_MODE,
        as_of=format_utc_timestamp(as_of_utc),
        period_start=start_day.isoformat(),
        period_end=as_of_day.isoformat(),
        status=status,
        total_resolved=len(entries),
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
        coverage={
            "legacy_resolutions_included": False,
            "legacy_full_fill_records": legacy_full_fill,
            "unfilled_trades": unfilled,
        },
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


def _parameters(config: PerformanceConfig, profile: CostProfile) -> dict[str, float | int | str]:
    return {
        "initial_cash": float(config.initial_cash),
        "risk_per_trade_pct": float(config.risk_per_trade_pct),
        "fee_rate": float(config.fee_rate),
        "slippage_rate": float(config.slippage_rate),
        "rf_annual": float(config.rf_annual),
        "periods_per_year": float(config.periods_per_year),
        "min_trades_for_ratios": int(config.min_trades_for_ratios),
        "cost_model_version": profile.version,
        "maker_fee_rate": float(profile.maker_fee_rate),
        "taker_fee_rate": float(profile.taker_fee_rate),
        "entry_liquidity": profile.entry_liquidity,
        "target_exit_liquidity": profile.target_exit_liquidity,
        "stop_exit_liquidity": profile.stop_exit_liquidity,
        "expiry_exit_liquidity": profile.expiry_exit_liquidity,
        "entry_slippage_rate": float(profile.entry_slippage_rate),
        "market_exit_slippage_rate": float(profile.market_exit_slippage_rate),
        "target_exit_slippage_rate": float(profile.target_exit_slippage_rate),
        "funding_rate_per_period": float(profile.funding_rate_per_period),
        "funding_period_hours": float(profile.funding_period_hours),
        "max_volume_participation": float(profile.max_volume_participation),
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
        "entry_quote_volume": None
        if record.entry_quote_volume is None
        else float(record.entry_quote_volume),
    }


def _data_hash(records: Sequence[ResolutionRecord]) -> str:
    payload = [_canonical_record(record) for record in records]
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _config_hash(parameters: dict[str, float | int | str]) -> str:
    text = json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
