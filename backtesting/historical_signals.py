from datetime import UTC, datetime, timedelta
from typing import Any

from common.constants import LONG_TERM_CONFIG
from domain.performance import (
    ClosedTrade,
    PnlTrade,
    fractions_from_pnl,
    profit_factor,
    summarize_closed_trades,
    win_rate,
)
from domain.signal_id import make_signal_id


async def generate_historical_signals(
    data: Any,
    symbol: str,
    timeframe: str,
    generator: Any,
    step: int = 1,
    include_external: bool = False,
    include_ml: bool = False,
) -> tuple[list[Any], dict[str, int]]:
    minimum = int(LONG_TERM_CONFIG.get("min_data_points", {}).get(timeframe, 300))
    start = max(minimum, 1)
    signals: list[Any] = []
    rejected = {"no_signal": 0, "errors": 0}
    for end in range(start, len(data), step):
        window = data.iloc[: end + 1]
        try:
            signal = await generator.generate_signal(
                symbol,
                timeframe,
                window,
                include_external=include_external,
                include_ml=include_ml,
            )
        except Exception:
            rejected["errors"] += 1
            continue
        if signal is None:
            rejected["no_signal"] += 1
        else:
            signals.append(signal)
    return signals, rejected


def candles_from_frame(frame: Any) -> list[dict]:
    rows = []
    for timestamp, row in frame.iterrows():
        stamp = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
        rows.append(
            {
                "timestamp": stamp,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
        )
    return rows


def simulator_inputs_from_signals(signals: list) -> list[dict]:
    inputs = []
    for signal in signals:
        stamp = signal.timestamp
        moment = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
        inputs.append(
            {
                "signal_id": make_signal_id(
                    signal.symbol, signal.timeframe, moment, signal.signal_type.value
                ),
                "side": signal.signal_type.value,
                "timestamp": moment,
                "stop": float(signal.stop_loss),
                "target": float(signal.exit_price),
            }
        )
    return inputs


def trade_metrics(
    trades: list,
    equity_start: float,
    *,
    periods_per_year: float = 365.0,
    rf_annual: float = 0.0,
) -> dict[str, float | None]:
    fractions = _trade_fractions(trades, equity_start)
    if not fractions:
        return {
            "trades_count": 0,
            "win_rate": win_rate([]),
            "profit_factor": profit_factor([]),
            "max_drawdown": 0.0,
            "sharpe": None,
            "sortino": None,
            "final_equity": float(equity_start),
        }
    start = min(trade.exit_at.astimezone(UTC).date() for trade in fractions)
    end = max(trade.exit_at.astimezone(UTC).date() for trade in fractions)
    summary = summarize_closed_trades(
        fractions,
        initial_equity=equity_start,
        start=start,
        end=end,
        periods_per_year=periods_per_year,
        rf_annual=rf_annual,
        min_trades_for_ratios=2,
    )
    fractions_only = [trade.return_fraction for trade in fractions]
    return {
        "trades_count": summary.total_closed,
        "win_rate": win_rate(fractions_only),
        "profit_factor": profit_factor(fractions_only),
        "max_drawdown": summary.max_drawdown,
        "sharpe": summary.sharpe,
        "sortino": summary.sortino,
        "final_equity": summary.final_equity,
    }


def _trade_fractions(trades: list, equity_start: float) -> list[ClosedTrade]:
    pnl_trades = []
    for index, trade in enumerate(trades):
        exit_at = getattr(trade, "exit_at", None)
        if not isinstance(exit_at, datetime):
            exit_at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
        signal_id = str(getattr(trade, "signal_id", None) or f"trade-{index}")
        pnl_trades.append(PnlTrade(exit_at, signal_id, float(trade.pnl)))
    return fractions_from_pnl(pnl_trades, equity_start)
