import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from backtesting.simulator import EventDrivenSimulator, SimulatorConfig
from config.settings import ConfigManager
from domain.costs import CostProfile, cost_profile_from_config
from strategy.signal_tracker import make_signal_id

EQUITY_START = 1_000_000.0
LEGACY_PATH = Path("tests/golden/backtest_baseline.json")
COST_V2_PATH = Path("tests/golden/backtest_cost_v2_baseline.json")


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


def default_cost_profile(
    config_manager: ConfigManager | None = None,
) -> CostProfile:
    defaults = ConfigManager.DEFAULT_CONFIG["paper_cost_model"]
    if config_manager is None:
        return cost_profile_from_config(defaults, defaults)
    return cost_profile_from_config(config_manager.get("paper_cost_model"), defaults)


def _build_report(config: SimulatorConfig, *, cost_model_version: str | None) -> dict:
    baseline = json.loads(Path("tests/golden/signals_baseline.json").read_text(encoding="utf-8"))
    simulator = EventDrivenSimulator(config)
    per_timeframe: dict[str, dict] = {}
    all_trades = []
    totals = {"signals_evaluated": 0, "size_zero": 0, "no_window": 0, "no_outcome": 0}
    unfilled_total = 0
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
        unfilled_total += stats.skipped_unfilled
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
    if cost_model_version is not None:
        profile = config.effective_profile()
        report["cost_model_version"] = cost_model_version
        report["skipped_unfilled"] = unfilled_total
        report["rejected"]["unfilled"] = unfilled_total
        report["cost_profile"] = {
            "version": profile.version,
            "maker_fee_rate": profile.maker_fee_rate,
            "taker_fee_rate": profile.taker_fee_rate,
            "entry_liquidity": profile.entry_liquidity,
            "target_exit_liquidity": profile.target_exit_liquidity,
            "stop_exit_liquidity": profile.stop_exit_liquidity,
            "expiry_exit_liquidity": profile.expiry_exit_liquidity,
            "entry_slippage_rate": profile.entry_slippage_rate,
            "market_exit_slippage_rate": profile.market_exit_slippage_rate,
            "target_exit_slippage_rate": profile.target_exit_slippage_rate,
            "funding_rate_per_period": profile.funding_rate_per_period,
            "funding_period_hours": profile.funding_period_hours,
            "max_volume_participation": profile.max_volume_participation,
        }
    return report


def _write(path: Path, report: dict) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")


def record_backtest_baseline() -> dict:
    report = _build_report(SimulatorConfig(), cost_model_version=None)
    _write(LEGACY_PATH, report)
    return report


def record_cost_v2_baseline(config_manager: ConfigManager | None = None) -> dict:
    profile = default_cost_profile(config_manager)
    report = _build_report(
        SimulatorConfig(cost_profile=profile), cost_model_version=profile.version
    )
    _write(COST_V2_PATH, report)
    return report


if __name__ == "__main__":
    print(json.dumps(record_backtest_baseline(), indent=2, sort_keys=True))
