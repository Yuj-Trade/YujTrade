import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from domain.costs import (
    CostProfile,
    cost_per_unit,
    fill_fraction,
    legacy_simulator_profile,
    net_r,
)
from domain.outcome import resolve_outcome
from domain.sizing import SizingConfig, calculate_position_size


@dataclass(frozen=True)
class SimulatorConfig:
    risk_per_trade_pct: float = 1.0
    max_single_position_pct: float = 10.0
    max_portfolio_exposure_pct: float = 60.0
    max_leverage: float = 3.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005
    exit_on_opposite_signal: bool = False
    cost_profile: CostProfile | None = None

    def effective_profile(self) -> CostProfile:
        if self.cost_profile is not None:
            return self.cost_profile
        return legacy_simulator_profile(self.commission_rate, self.slippage_rate)


@dataclass(frozen=True)
class SimulatedTrade:
    signal_id: str
    side: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    exit_reason: str
    qty: float
    fee: float
    pnl: float
    r_multiple: float


@dataclass(frozen=True)
class RunStats:
    signals_evaluated: int = 0
    skipped_no_window: int = 0
    skipped_size_zero: int = 0
    skipped_no_outcome: int = 0
    skipped_unfilled: int = 0


class EventDrivenSimulator:
    def __init__(self, config: SimulatorConfig | None = None) -> None:
        self.config = config or SimulatorConfig()

    def run(
        self,
        candles: Sequence[Mapping[str, object]],
        signals: Iterable[Mapping[str, object]],
        equity: float,
    ) -> list[SimulatedTrade]:
        trades, _ = self.run_with_stats(candles, signals, equity)
        return trades

    def run_with_stats(
        self,
        candles: Sequence[Mapping[str, object]],
        signals: Iterable[Mapping[str, object]],
        equity: float,
    ) -> tuple[list[SimulatedTrade], RunStats]:
        profile = self.config.effective_profile()
        if profile.version == "legacy-simulator-v1":
            return self._run_legacy(candles, signals, equity)
        return self._run_v2(candles, signals, equity, profile)

    def _run_legacy(
        self,
        candles: Sequence[Mapping[str, object]],
        signals: Iterable[Mapping[str, object]],
        equity: float,
    ) -> tuple[list[SimulatedTrade], RunStats]:
        bars = list(candles)
        by_time = {self._timestamp(candle): index for index, candle in enumerate(bars)}
        trades: list[SimulatedTrade] = []
        exposure = 0.0
        evaluated = 0
        no_window = 0
        size_zero = 0
        no_outcome = 0
        sizing = SizingConfig(
            self.config.risk_per_trade_pct,
            self.config.max_single_position_pct,
            self.config.max_portfolio_exposure_pct,
            self.config.max_leverage,
        )
        for raw_signal in signals:
            evaluated += 1
            signal_time = self._timestamp(raw_signal)
            index = by_time.get(signal_time)
            if index is None or index + 1 >= len(bars):
                no_window += 1
                continue
            side = str(raw_signal["side"]).lower()
            entry = float(bars[index + 1]["open"])
            entry = entry * (
                1.0 + self.config.slippage_rate
                if side == "buy"
                else 1.0 - self.config.slippage_rate
            )
            stop = float(raw_signal["stop"])
            target = float(raw_signal["target"])
            result = calculate_position_size(equity, entry, stop, sizing, current_exposure=exposure)
            if result.quantity <= 0:
                size_zero += 1
                continue
            window = bars[index + 1 :]
            outcome = resolve_outcome(
                window, side, entry, stop, target, created_at=None, expiry_hours=None
            )
            if outcome is None:
                no_outcome += 1
                continue
            exit_index = self._find_exit(window, outcome.exit_price, side, stop, target)
            exit_bar = window[exit_index]
            exit_price = float(outcome.exit_price)
            exit_open = float(exit_bar["open"])
            if outcome.reason == "stop" and (
                (side == "buy" and exit_open < stop) or (side == "sell" and exit_open > stop)
            ):
                exit_price = exit_open
            fee = (entry + exit_price) * result.quantity * self.config.commission_rate
            gross = (
                (exit_price - entry) * result.quantity
                if side == "buy"
                else (entry - exit_price) * result.quantity
            )
            risk = abs(entry - stop) * result.quantity
            trades.append(
                SimulatedTrade(
                    str(raw_signal.get("signal_id", "")),
                    side,
                    self._timestamp(bars[index + 1]),
                    entry,
                    self._timestamp(exit_bar),
                    exit_price,
                    outcome.reason,
                    result.quantity,
                    fee,
                    gross - fee,
                    (gross - fee) / risk if risk else 0.0,
                )
            )
            exposure += entry * result.quantity
        stats = RunStats(
            signals_evaluated=evaluated,
            skipped_no_window=no_window,
            skipped_size_zero=size_zero,
            skipped_no_outcome=no_outcome,
        )
        return trades, stats

    def _run_v2(
        self,
        candles: Sequence[Mapping[str, object]],
        signals: Iterable[Mapping[str, object]],
        equity: float,
        profile: CostProfile,
    ) -> tuple[list[SimulatedTrade], RunStats]:
        bars = list(candles)
        by_time = {self._timestamp(candle): index for index, candle in enumerate(bars)}
        trades: list[SimulatedTrade] = []
        exposure = 0.0
        evaluated = 0
        no_window = 0
        size_zero = 0
        no_outcome = 0
        unfilled = 0
        sizing = SizingConfig(
            self.config.risk_per_trade_pct,
            self.config.max_single_position_pct,
            self.config.max_portfolio_exposure_pct,
            self.config.max_leverage,
        )
        for raw_signal in signals:
            evaluated += 1
            signal_time = self._timestamp(raw_signal)
            index = by_time.get(signal_time)
            if index is None or index + 1 >= len(bars):
                no_window += 1
                continue
            side = str(raw_signal["side"]).lower()
            entry_bar = bars[index + 1]
            entry = float(entry_bar["open"])
            stop = float(raw_signal["stop"])
            target = float(raw_signal["target"])
            result = calculate_position_size(equity, entry, stop, sizing, current_exposure=exposure)
            if result.quantity <= 0:
                size_zero += 1
                continue
            notional = result.quantity * entry
            quote_volume = float(entry_bar.get("volume") or 0.0) * entry
            ratio = fill_fraction(notional, quote_volume, profile.max_volume_participation)
            if ratio == 0.0:
                unfilled += 1
                continue
            window = bars[index + 1 :]
            outcome = resolve_outcome(
                window, side, entry, stop, target, created_at=None, expiry_hours=None
            )
            if outcome is None:
                no_outcome += 1
                continue
            exit_index = self._find_exit(window, outcome.exit_price, side, stop, target)
            exit_bar = window[exit_index]
            exit_price = float(outcome.exit_price)
            exit_open = float(exit_bar["open"])
            if outcome.reason == "stop" and (
                (side == "buy" and exit_open < stop) or (side == "sell" and exit_open > stop)
            ):
                exit_price = exit_open
            entry_time = self._timestamp(entry_bar)
            exit_time = self._timestamp(exit_bar)
            holding_hours = max(0.0, (exit_time - entry_time).total_seconds() / 3600.0)
            filled_qty = result.quantity * ratio
            cost_unit = cost_per_unit(entry, exit_price, outcome.reason, holding_hours, profile)
            fee = cost_unit * filled_qty
            gross = (
                (exit_price - entry) * filled_qty
                if side == "buy"
                else (entry - exit_price) * filled_qty
            )
            risk = abs(entry - stop) * filled_qty
            r_multiple = net_r(
                entry,
                stop,
                exit_price,
                side,
                outcome.reason,
                holding_hours,
                profile,
                ratio,
            )
            trades.append(
                SimulatedTrade(
                    str(raw_signal.get("signal_id", "")),
                    side,
                    entry_time,
                    entry,
                    exit_time,
                    exit_price,
                    outcome.reason,
                    filled_qty,
                    fee,
                    gross - fee,
                    r_multiple if risk else 0.0,
                )
            )
            exposure += entry * filled_qty
        stats = RunStats(
            signals_evaluated=evaluated,
            skipped_no_window=no_window,
            skipped_size_zero=size_zero,
            skipped_no_outcome=no_outcome,
            skipped_unfilled=unfilled,
        )
        return trades, stats

    @staticmethod
    def _timestamp(value: Mapping[str, object]) -> datetime:
        timestamp = value.get("timestamp") or value.get("time")
        if not isinstance(timestamp, datetime):
            raise TypeError("candle and signal timestamps must be datetime values")
        return timestamp

    @staticmethod
    def _find_exit(
        candles: Sequence[Mapping[str, object]],
        exit_price: float,
        side: str,
        stop: float,
        target: float,
    ) -> int:
        for index, candle in enumerate(candles):
            high = float(candle["high"])
            low = float(candle["low"])
            if side == "buy" and low <= stop:
                return index
            if side == "sell" and high >= stop:
                return index
            if side == "buy" and high >= target:
                return index
            if side == "sell" and low <= target:
                return index
        return 0


def write_trades_csv(path: str | Path, trades: Iterable[SimulatedTrade]) -> None:
    fields = [
        "signal_id",
        "side",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "exit_reason",
        "qty",
        "fee",
        "pnl",
        "r_multiple",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({field: getattr(trade, field) for field in fields})
