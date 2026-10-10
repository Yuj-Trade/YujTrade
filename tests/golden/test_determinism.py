import asyncio
import hashlib
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_baselines_reproduce_byte_identical():
    signals_path = ROOT / "tests/golden/signals_baseline.json"
    backtest_path = ROOT / "tests/golden/backtest_baseline.json"
    assert signals_path.exists()
    assert backtest_path.exists()
    before = (_sha256(signals_path), _sha256(backtest_path))

    recorder = _load("golden_signal_recorder", "tests/golden/record_signals.py")
    asyncio.run(recorder.record_signals_baseline())
    backtest = _load("golden_backtest_recorder", "scripts/record_backtest.py")
    backtest.record_backtest_baseline()

    assert _sha256(signals_path) == before[0]
    assert _sha256(backtest_path) == before[1]


def test_baseline_files_use_sorted_keys():
    import json

    for name in ("tests/golden/signals_baseline.json", "tests/golden/backtest_baseline.json"):
        raw = (ROOT / name).read_bytes()
        assert raw.endswith(b"\n")
        assert b"\r" not in raw
        payload = json.loads(raw.decode("utf-8"))
        canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        assert raw == canonical
