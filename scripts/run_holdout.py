import argparse
import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.historical_signals import (
    candles_from_frame,
    generate_historical_signals,
    simulator_inputs_from_signals,
)
from backtesting.historical_signals import (
    trade_metrics as shared_trade_metrics,
)
from backtesting.montecarlo import bootstrap_confidence_interval, simulate_r_multiples
from backtesting.simulator import EventDrivenSimulator
from backtesting.walk_forward import HoldoutGuard
from common.constants import LONG_TERM_CONFIG
from config.settings import ConfigManager
from data.data_validator import DataQualityChecker
from modeling.artifacts import ArtifactRegistry
from strategy.signal_generator import SignalGenerator

EQUITY_START = 1_000_000.0


def _disable_freshness_for_historical_csv() -> None:
    DataQualityChecker._check_data_freshness = lambda self, data, timeframe: True


_disable_freshness_for_historical_csv()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unknown"


class _CsvProvider:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    async def fetch_ohlcv_data(self, symbol, timeframe, limit=1000, bypass_cache=False):
        return self._frame.tail(limit)

    async def get_data_for_model(self, symbol, timeframe, for_prediction=False):
        return self._frame.tail(300)

    def __getattr__(self, name):
        if name.startswith("get_"):

            async def _none(*args, **kwargs):
                return None

            return _none
        raise AttributeError(name)


class _NoModelManager:
    async def predict_with_confidence(self, model_type, symbol, timeframe):
        return None

    async def record_signal_performance(self, model_type, symbol, timeframe, confidence, success):
        pass


def _assert_no_ml_leakage(
    symbol: str,
    timeframe: str,
    holdout_start: pd.Timestamp,
    artifact_root: str | Path = "artifacts",
) -> None:
    registry = ArtifactRegistry(artifact_root)
    checked = 0
    for model_type in ("lstm", "xgboost"):
        directory = registry.current_dir(model_type, symbol, timeframe)
        if directory is None:
            continue
        checked += 1
        payload = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        data_end = payload.get("data_end")
        if not data_end:
            raise ValueError(f"ML artifact for {model_type} has no data_end; --with-ml refused")
        end = datetime.fromisoformat(str(data_end))
        start = (
            holdout_start.to_pydatetime()
            if hasattr(holdout_start, "to_pydatetime")
            else holdout_start
        )
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end >= start:
            raise ValueError(
                f"ML artifact for {model_type} trained on data ending {data_end}, "
                "inside the holdout window; --with-ml refused"
            )
    if checked == 0:
        raise ValueError("No current ML artifact found; --with-ml refused")


def _candles(frame: pd.DataFrame) -> list[dict]:
    return candles_from_frame(frame)


def _simulator_inputs(signals: list) -> list[dict]:
    return simulator_inputs_from_signals(signals)


def _trade_metrics(trades: list, equity_start: float) -> dict[str, float]:
    metrics = shared_trade_metrics(trades, equity_start)
    simulated = simulate_r_multiples([float(trade.r_multiple) for trade in trades])
    ordered = sorted(simulated)
    if ordered:
        lower = ordered[max(0, int(0.025 * len(ordered)) - 1)]
        upper = ordered[min(len(ordered) - 1, int(0.975 * len(ordered)))]
        bootstrap_ci_95 = [float(lower), float(upper)]
    else:
        bootstrap_ci_95 = [0.0, 0.0]
    metrics["bootstrap_ci_95"] = bootstrap_ci_95
    metrics["monte_carlo"] = bootstrap_confidence_interval(
        [float(trade.r_multiple) for trade in trades]
    )
    return metrics


def run_holdout(
    data_path: str | Path,
    state_path: str | Path,
    confirm: bool = False,
    force_rerun: bool = False,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    out: str | Path | None = None,
    with_ml: bool = False,
    artifact_root: str | Path = "artifacts",
    model_path: str | Path = "models",
) -> dict[str, object]:
    path = Path(data_path)
    data = pd.read_csv(path, index_col=0, parse_dates=True)
    config = {
        "data_path": str(path.resolve()),
        "holdout_fraction": 0.15,
        "symbol": symbol,
        "timeframe": timeframe,
        "with_ml": with_ml,
    }
    guard = HoldoutGuard(data, state_path=state_path, config=config)
    holdout = guard.consume(confirm=confirm, force_rerun=force_rerun)
    development = guard.development
    if with_ml:
        _assert_no_ml_leakage(symbol, timeframe, holdout.index[0], artifact_root)

    warmup = min(
        len(development), int(LONG_TERM_CONFIG.get("min_data_points", {}).get(timeframe, 300))
    )
    frame = pd.concat([development.tail(warmup), holdout])

    config_manager = ConfigManager()
    provider = _CsvProvider(data)
    if with_ml:
        from modeling.model_manager import ModelManager

        model_manager = ModelManager(provider, model_path=str(model_path))
    else:
        model_manager = _NoModelManager()
    generator = SignalGenerator(provider, model_manager, config_manager)
    signals, rejected = asyncio.run(
        generate_historical_signals(frame, symbol, timeframe, generator, include_ml=with_ml)
    )

    candles = _candles(frame)
    simulator = EventDrivenSimulator()
    trades, stats = simulator.run_with_stats(candles, _simulator_inputs(signals), EQUITY_START)
    metrics = _trade_metrics(trades, EQUITY_START)
    close = holdout["close"].astype(float)
    buy_and_hold_return = float(close.iloc[-1] / close.iloc[0] - 1.0)
    result: dict[str, object] = {
        "rows": int(len(holdout)),
        "data_hash": guard.data_hash,
        "config_hash": guard.config_hash,
        "start": holdout.index[0].isoformat(),
        "end": holdout.index[-1].isoformat(),
        "return": buy_and_hold_return,
        "buy_and_hold_return": buy_and_hold_return,
        "forced": force_rerun,
        "symbol": symbol,
        "timeframe": timeframe,
        "with_ml": with_ml,
        "warmup_rows": int(warmup),
        "signals_count": len(signals),
        "rejected": rejected,
        "simulator_rejected": {
            "no_window": stats.skipped_no_window,
            "no_outcome": stats.skipped_no_outcome,
            "size_zero": stats.skipped_size_zero,
        },
        "equity_start": EQUITY_START,
        "git_commit": _git_commit(),
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
    }
    result.update(metrics)
    target = (
        Path(out)
        if out
        else Path("runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") / "holdout_report.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["report_path"] = str(target)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the protected local holdout.")
    parser.add_argument("data", type=Path, help="Local OHLCV CSV")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--state", type=Path, default=Path("runs/holdout_used.json"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--with-ml", action="store_true")
    args = parser.parse_args()
    result = run_holdout(
        args.data,
        args.state,
        args.confirm,
        args.force_rerun,
        symbol=args.symbol,
        timeframe=args.timeframe,
        out=args.out,
        with_ml=args.with_ml,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
