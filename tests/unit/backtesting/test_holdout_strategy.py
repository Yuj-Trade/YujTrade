import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[3]


def _load_run_holdout():
    spec = importlib.util.spec_from_file_location(
        "run_holdout_strategy", ROOT / "scripts/run_holdout.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_historical_signals():
    spec = importlib.util.spec_from_file_location(
        "historical_signals", ROOT / "backtesting/historical_signals.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tiny_csv(path: Path) -> Path:
    dates = pd.date_range("2024-01-01", periods=120, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        },
        index=dates,
    )
    frame.to_csv(path)
    return path


def _generator(module, frame):
    from config.settings import ConfigManager
    from strategy.signal_generator import SignalGenerator

    provider = module._CsvProvider(frame)
    return SignalGenerator(provider, module._NoModelManager(), ConfigManager())


def test_holdout_report_has_all_keys_and_trades(tmp_path):
    module = _load_run_holdout()
    out = tmp_path / "report.json"
    state = tmp_path / "state.json"
    result = module.run_holdout(
        ROOT / "tests/fixtures/ohlcv_1h.csv",
        state,
        confirm=True,
        symbol="BTC/USDT",
        timeframe="1h",
        out=out,
    )
    for key in (
        "rows",
        "data_hash",
        "config_hash",
        "trades_count",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "sharpe",
        "final_equity",
        "buy_and_hold_return",
        "rejected",
        "git_commit",
        "evaluated_at_utc",
    ):
        assert key in result, key
    assert result["trades_count"] >= 1
    assert out.exists()
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert stored["trades_count"] == result["trades_count"]


def test_holdout_guardrails_without_confirm_single_use_and_rerun(tmp_path):
    module = _load_run_holdout()
    csv = _tiny_csv(tmp_path / "ohlcv.csv")
    state = tmp_path / "state.json"
    out = tmp_path / "report.json"
    with pytest.raises(PermissionError):
        module.run_holdout(csv, state, confirm=False, out=out)
    module.run_holdout(csv, state, confirm=True, out=out)
    with pytest.raises(RuntimeError):
        module.run_holdout(csv, state, confirm=True, out=out)
    forced = module.run_holdout(csv, state, confirm=True, force_rerun=True, out=out)
    assert forced["forced"] is True


def test_historical_signals_are_causal(tmp_path):
    historical = _load_historical_signals()
    module = _load_run_holdout()
    frame = pd.read_csv(ROOT / "tests/fixtures/ohlcv_1h.csv", index_col=0, parse_dates=True)
    prefix = frame.iloc[:700].copy()
    altered_tail = frame.iloc[700:800].copy()
    altered_tail[["open", "high", "low", "close"]] *= 2.0
    extended = pd.concat([frame.iloc[:700], altered_tail])

    import asyncio

    async def _run(data):
        generator = _generator(module, data)
        return await historical.generate_historical_signals(data, "BTC/USDT", "1h", generator)

    first, _ = asyncio.run(_run(prefix))
    second, _ = asyncio.run(_run(extended))
    cutoff = prefix.index[-1]
    past_first = [s for s in first if s.timestamp <= cutoff]
    past_second = [s for s in second if s.timestamp <= cutoff]
    assert len(past_first) == len(past_second)
    for left, right in zip(past_first, past_second, strict=False):
        assert left.symbol == right.symbol
        assert left.timeframe == right.timeframe
        assert left.timestamp == right.timestamp
        assert left.signal_type == right.signal_type
        assert left.entry_price == right.entry_price
        assert left.stop_loss == right.stop_loss
        assert left.exit_price == right.exit_price


def test_with_ml_refuses_missing_artifact(tmp_path):
    module = _load_run_holdout()
    csv = _tiny_csv(tmp_path / "ohlcv.csv")
    with pytest.raises(ValueError, match="No current ML artifact"):
        module.run_holdout(
            csv,
            tmp_path / "state.json",
            confirm=True,
            out=tmp_path / "report.json",
            with_ml=True,
            artifact_root=tmp_path / "artifacts",
            model_path=tmp_path / "models",
        )


def test_with_ml_refuses_artifact_overlapping_holdout(tmp_path):
    module = _load_run_holdout()
    csv = _tiny_csv(tmp_path / "ohlcv.csv")
    data = pd.read_csv(csv, index_col=0, parse_dates=True)
    cut = int(len(data) * 0.85)
    holdout_start = data.index[cut]

    from modeling.artifacts import ArtifactRegistry, build_metadata

    registry = ArtifactRegistry(tmp_path / "artifacts")
    source = tmp_path / "model.json"
    source.write_text("{}", encoding="utf-8")
    leaking = pd.DataFrame(
        {"close": [1.0, 2.0]},
        index=pd.DatetimeIndex([holdout_start, holdout_start + pd.Timedelta(hours=1)]),
    )
    metadata = build_metadata(leaking, ["close"], {"p": 1}, {}, source_files=[source])
    registry.create_version("lstm", "BTC/USDT", "1h", [source], metadata=metadata)

    with pytest.raises(ValueError, match="inside the holdout window"):
        module.run_holdout(
            csv,
            tmp_path / "state.json",
            confirm=True,
            out=tmp_path / "report.json",
            with_ml=True,
            artifact_root=tmp_path / "artifacts",
            model_path=tmp_path / "models",
        )
