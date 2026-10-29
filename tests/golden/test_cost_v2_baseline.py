import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests/golden/backtest_cost_v2_baseline.json"


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_v2_baseline_reproduces_byte_identical():
    assert BASELINE.exists()
    before_bytes = BASELINE.read_bytes()

    recorder = _load("record_backtest_v2", "scripts/record_backtest.py")
    report = recorder.record_cost_v2_baseline()

    after_bytes = BASELINE.read_bytes()
    assert after_bytes == before_bytes
    assert report["cost_model_version"] == "cost-model-v2"
    assert report["trades_count"] >= 5
    assert report["signals_evaluated"] > 0


def test_the_v2_baseline_uses_sorted_keys():
    raw = BASELINE.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    payload = json.loads(raw.decode("utf-8"))
    canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    assert raw == canonical


def test_the_v2_baseline_records_the_profile():
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    profile = payload["cost_profile"]
    assert profile["version"] == "cost-model-v2"
    assert profile["maker_fee_rate"] == 0.001
    assert profile["max_volume_participation"] == 0.05
    assert "skipped_unfilled" in payload


def test_the_legacy_recorder_output_is_unchanged():
    legacy_path = ROOT / "tests/golden/backtest_baseline.json"
    before = legacy_path.read_bytes()

    recorder = _load("record_backtest_legacy", "scripts/record_backtest.py")
    recorder.record_backtest_baseline()

    assert legacy_path.read_bytes() == before
    payload = json.loads(before.decode("utf-8"))
    assert "cost_model_version" not in payload
