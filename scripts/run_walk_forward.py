import argparse
import asyncio
import json
import math
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.historical_signals import (
    candles_from_frame,
    generate_historical_signals,
    simulator_inputs_from_signals,
    trade_metrics,
)
from backtesting.simulator import EventDrivenSimulator, SimulatorConfig
from backtesting.walk_forward import WalkForwardValidator
from config.settings import ConfigManager
from data.data_validator import DataQualityChecker
from domain.costs import cost_profile_from_config
from strategy.signal_generator import SignalGenerator

WALK_FORWARD_SCHEMA_VERSION = 1
EQUITY_START = 1_000_000.0
DEFAULT_FOLDS = 4
DEFAULT_MIN_TRAIN_FRACTION = 0.6
DEFAULT_STEP = 4


def _simulator_config() -> SimulatorConfig:
    defaults = ConfigManager.DEFAULT_CONFIG["paper_cost_model"]
    profile = cost_profile_from_config(ConfigManager().get("paper_cost_model"), defaults)
    return SimulatorConfig(cost_profile=profile)


def _disable_freshness_for_historical_csv() -> None:
    DataQualityChecker._check_data_freshness = lambda self, data, timeframe: True


_disable_freshness_for_historical_csv()


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


def _build_generator(frame: pd.DataFrame, symbol: str, timeframe: str) -> SignalGenerator:
    config_manager = ConfigManager()
    provider = _CsvProvider(frame)
    return SignalGenerator(provider, _NoModelManager(), config_manager)


def _fold_hygiene(train_positions, test_positions) -> dict[str, Any]:
    train_set = set(int(position) for position in train_positions)
    test_set = set(int(position) for position in test_positions)
    overlap = train_set & test_set
    leakage_flags = len(overlap)
    if train_set and test_set:
        if max(train_set) >= min(test_set):
            leakage_flags += 1
        gap = min(test_set) - max(train_set) - 1
    else:
        gap = 0
    return {
        "train_size": len(train_set),
        "test_size": len(test_set),
        "overlap": len(overlap),
        "gap": int(gap),
        "leakage_flags": int(leakage_flags),
    }


def _finite(value: float | None) -> bool:
    if value is None:
        return False
    return not (math.isnan(value) or math.isinf(value))


def run_walk_forward(
    data_path: str | Path,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    folds: int = DEFAULT_FOLDS,
    min_train_fraction: float = DEFAULT_MIN_TRAIN_FRACTION,
    step: int = DEFAULT_STEP,
    warmup_bars: int = 0,
    sequence_length: int = 0,
    out: str | Path | None = None,
    generator: Any = None,
) -> dict[str, Any]:
    path = Path(data_path)
    data = pd.read_csv(path, index_col=0, parse_dates=True)
    validator = WalkForwardValidator(
        folds=folds,
        min_train_fraction=min_train_fraction,
        label_horizon=1,
        warmup_bars=warmup_bars,
        sequence_length=sequence_length,
    )
    splits = validator.split(data)

    active_generator = generator or _build_generator(data, symbol, timeframe)
    signals, rejected = asyncio.run(
        generate_historical_signals(
            data,
            symbol,
            timeframe,
            active_generator,
            step=1,
            include_external=False,
            include_ml=False,
        )
    )

    simulator = EventDrivenSimulator(_simulator_config())
    fold_reports: list[dict[str, Any]] = []
    leakage_total = 0
    for fold in splits:
        train_index = list(fold.train.index)
        test_index = list(fold.test.index)
        train_positions = data.index.get_indexer(train_index)
        test_positions = data.index.get_indexer(test_index)
        hygiene = _fold_hygiene(train_positions, test_positions)
        leakage_total += hygiene["leakage_flags"]

        test_position_set = set(int(position) for position in test_positions)
        fold_signals = []
        for signal in signals:
            positions = data.index.get_indexer([signal.timestamp])
            if positions[0] >= 0 and int(positions[0]) in test_position_set:
                fold_signals.append(signal)
        candle_frame = data.loc[: test_index[-1]] if test_index else data
        candles = candles_from_frame(candle_frame)
        trades, stats = simulator.run_with_stats(
            candles, simulator_inputs_from_signals(fold_signals), EQUITY_START
        )
        metrics = trade_metrics(trades, EQUITY_START)
        if test_index:
            closes = data.loc[test_index, "close"].astype(float)
            buy_and_hold = float(closes.iloc[-1] / closes.iloc[0] - 1.0) if len(closes) > 1 else 0.0
        else:
            buy_and_hold = 0.0
        finite = all(value is None or _finite(float(value)) for value in metrics.values())
        fold_reports.append(
            {
                "index": fold.index,
                "hygiene": hygiene,
                "signals_count": len(fold_signals),
                "metrics": metrics,
                "buy_and_hold_return": buy_and_hold,
                "simulator_rejected": {
                    "no_window": stats.skipped_no_window,
                    "no_outcome": stats.skipped_no_outcome,
                    "size_zero": stats.skipped_size_zero,
                },
                "metrics_finite": finite,
            }
        )

    metrics_hash = sha256(
        json.dumps(
            [
                {
                    "index": report["index"],
                    "metrics": report["metrics"],
                    "buy_and_hold_return": report["buy_and_hold_return"],
                }
                for report in fold_reports
            ],
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    report: dict[str, Any] = {
        "schema_version": WALK_FORWARD_SCHEMA_VERSION,
        "data_path": str(path.resolve()),
        "data_hash": sha256(path.read_bytes()).hexdigest(),
        "symbol": symbol,
        "timeframe": timeframe,
        "folds_requested": folds,
        "folds_evaluated": len(fold_reports),
        "step": step,
        "signals_total": len(signals),
        "rejected": rejected,
        "leakage_flags": int(leakage_total),
        "metrics_finite": all(report["metrics_finite"] for report in fold_reports),
        "metrics_hash": metrics_hash,
        "folds": fold_reports,
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
    }

    target = (
        Path(out)
        if out
        else Path("runs")
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        / "walk_forward_report.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["report_path"] = str(target)
    return report


def _validate(report: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if report["leakage_flags"] != 0:
        problems.append(f"leakage_flags={report['leakage_flags']}")
    if not report["metrics_finite"]:
        problems.append("non_finite_metrics")
    if report["folds_evaluated"] == 0:
        problems.append("no_folds_evaluated")
    for fold in report["folds"]:
        if fold["hygiene"]["overlap"] != 0:
            problems.append(f"fold{fold['index']}:overlap")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run walk-forward validation on a local OHLCV CSV."
    )
    parser.add_argument("data", type=Path, help="Local OHLCV CSV")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    parser.add_argument("--min-train-fraction", type=float, default=DEFAULT_MIN_TRAIN_FRACTION)
    parser.add_argument("--step", type=int, default=DEFAULT_STEP)
    parser.add_argument("--warmup-bars", type=int, default=0)
    parser.add_argument("--sequence-length", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    report = run_walk_forward(
        args.data,
        symbol=args.symbol,
        timeframe=args.timeframe,
        folds=args.folds,
        min_train_fraction=args.min_train_fraction,
        step=args.step,
        warmup_bars=args.warmup_bars,
        sequence_length=args.sequence_length,
        out=args.out,
    )
    problems = _validate(report)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "folds"},
            indent=2,
            sort_keys=True,
        )
    )
    if problems:
        print(f"walk-forward validation failed: {problems}")
        raise SystemExit(1)
    print(f"walk-forward validation passed: {report['folds_evaluated']} folds, 0 leakage flags")


if __name__ == "__main__":
    main()
