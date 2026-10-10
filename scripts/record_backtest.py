import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from backtesting.simulator import EventDrivenSimulator, SimulatorConfig
from strategy.signal_tracker import make_signal_id

EQUITY_START = 10000.0


def _candles(frame: pd.DataFrame) -> list[dict]:
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


def _simulator_inputs(records: list[dict]) -> list[dict]:
    inputs = []
    for record in records:
        stamp = record["timestamp"]
        moment = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
        inputs.append(
            {
                "signal_id": make_signal_id(
                    record["symbol"], record["timeframe"], moment, record["signal_type"]
                ),
                "side": record["signal_type"],
                "timestamp": moment,
                "stop": float(record["stop"]),
                "target": float(record["target"]),
            }
        )
    return inputs


def record_backtest_baseline() -> dict:
    baseline = json.loads(Path("tests/golden/signals_baseline.json").read_text(encoding="utf-8"))
    config = SimulatorConfig()
    simulator = EventDrivenSimulator(config)
    per_timeframe: dict[str, dict] = {}
    all_trades = []
    totals = {"signals_evaluated": 0, "size_zero": 0, "no_window": 0, "no_outcome": 0}
    for timeframe in ("1h", "1d"):
        frame = pd.read_csv(f"tests/fixtures/ohlcv_{timeframe}.csv", index_col=0, parse_dates=True)
        candles = _candles(frame)
        scoped = [r for r in baseline if r.get("timeframe", "1h") == timeframe]
        trades, stats = simulator.run_with_stats(candles, _simulator_inputs(scoped), EQUITY_START)
        all_trades.extend(trades)
        totals["signals_evaluated"] += stats.signals_evaluated
        totals["size_zero"] += stats.skipped_size_zero
        totals["no_window"] += stats.skipped_no_window
        totals["no_outcome"] += stats.skipped_no_outcome
        per_timeframe[timeframe] = {
            "signals_evaluated": stats.signals_evaluated,
            "trades_count": len(trades),
        }
    final_capital = EQUITY_START + sum(t.pnl for t in all_trades)
    report = {
        "equity_start": EQUITY_START,
        "signals_evaluated": totals["signals_evaluated"],
        "trades_count": len(all_trades),
        "final_capital": final_capital,
        "rejected": {
            "no_window": totals["no_window"],
            "no_outcome": totals["no_outcome"],
            "size_zero": totals["size_zero"],
        },
        "per_timeframe": per_timeframe,
        "simulator_config": {
            "commission_rate": config.commission_rate,
            "slippage_rate": config.slippage_rate,
            "risk_per_trade_pct": config.risk_per_trade_pct,
            "exit_on_opposite_signal": config.exit_on_opposite_signal,
        },
    }
    output = Path("tests/golden/backtest_baseline.json")
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(record_backtest_baseline(), indent=2, sort_keys=True))
