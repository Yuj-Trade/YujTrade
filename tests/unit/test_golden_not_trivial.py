import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]


def _signals():
    return json.loads((ROOT / "tests/golden/signals_baseline.json").read_text(encoding="utf-8"))


def _backtest():
    return json.loads((ROOT / "tests/golden/backtest_baseline.json").read_text(encoding="utf-8"))


def test_signals_golden_is_not_empty():
    assert len(_signals()) >= 10


def test_signals_golden_has_both_sides_on_each_timeframe():
    signals = _signals()
    for timeframe in ("1h", "1d"):
        scoped = [s for s in signals if s["timeframe"] == timeframe]
        assert sum(1 for s in scoped if s["signal_type"] == "buy") >= 5
        assert sum(1 for s in scoped if s["signal_type"] == "sell") >= 5


def test_backtest_golden_has_trades():
    assert _backtest()["trades_count"] >= 5


def test_backtest_golden_evaluated_both_timeframes():
    per_tf = _backtest()["per_timeframe"]
    assert per_tf["1h"]["signals_evaluated"] > 0
    assert per_tf["1d"]["signals_evaluated"] > 0
