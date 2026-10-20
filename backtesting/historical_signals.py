from statistics import mean, pstdev
from typing import Any

from common.constants import LONG_TERM_CONFIG
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


def trade_metrics(trades: list, equity_start: float) -> dict[str, float]:
    pnls = [float(trade.pnl) for trade in trades]
    wins = sum(1 for pnl in pnls if pnl > 0)
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = -sum(pnl for pnl in pnls if pnl < 0)
    equity = equity_start
    peak = equity_start
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    if len(pnls) > 1 and pstdev(pnls) > 0:
        sharpe = float(mean(pnls) / pstdev(pnls) * (len(pnls) ** 0.5))
    else:
        sharpe = 0.0
    return {
        "trades_count": len(pnls),
        "win_rate": (wins / len(pnls)) if pnls else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else 0.0,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "final_equity": equity_start + sum(pnls),
    }
