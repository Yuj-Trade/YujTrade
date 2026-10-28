import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]


def load_record_backtest():
    spec = importlib.util.spec_from_file_location(
        "record_backtest", ROOT / "scripts/record_backtest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candles_helper_converts_frame_types():
    module = load_record_backtest()
    dates = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [5.0, 6.0],
        },
        index=dates,
    )
    rows = module._candles(frame)
    assert len(rows) == 2
    assert isinstance(rows[0]["timestamp"], datetime)
    assert rows[0]["high"] == 102.0
    assert rows[1]["close"] == 102.0


def test_simulator_inputs_helper_parses_iso_strings():
    module = load_record_backtest()
    records = [
        {
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "signal_type": "buy",
            "timestamp": "2024-01-01T05:00:00+00:00",
            "stop": 95.0,
            "target": 110.0,
        }
    ]
    inputs = module._simulator_inputs(records)
    assert inputs[0]["signal_id"] == "BTC/USDT|1h|2024-01-01T05:00:00+00:00|buy"
    assert inputs[0]["side"] == "buy"
    assert isinstance(inputs[0]["timestamp"], datetime)
    assert inputs[0]["timestamp"] == datetime(2024, 1, 1, 5, tzinfo=UTC)
    assert inputs[0]["stop"] == 95.0
    assert inputs[0]["target"] == 110.0


def test_simulator_inputs_accepts_datetime_objects():
    module = load_record_backtest()
    records = [
        {
            "symbol": "ETH/USDT",
            "timeframe": "1d",
            "signal_type": "sell",
            "timestamp": datetime(2024, 3, 1, tzinfo=UTC),
            "stop": 3100.0,
            "target": 2700.0,
        }
    ]
    inputs = module._simulator_inputs(records)
    assert isinstance(inputs[0]["timestamp"], datetime)
    assert inputs[0]["signal_id"] == "ETH/USDT|1d|2024-03-01T00:00:00+00:00|sell"


def test_baseline_files_exist_for_recording():
    baseline = ROOT / "tests/golden/signals_baseline.json"
    backtest = ROOT / "tests/golden/backtest_baseline.json"
    assert baseline.exists()
    assert backtest.exists()
    payload = __import__("json").loads(baseline.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert all("timeframe" in record for record in payload)
    report = __import__("json").loads(backtest.read_text(encoding="utf-8"))
    assert report["equity_start"] == 1_000_000.0
