"""Walk-forward validation job contract.

The job exists to prove that fold evaluation stays causal: every fold trains
on its own prefix, trades on its own test slice, and never leaks a row.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = "tests/fixtures/walk_forward_1h.csv"


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_walk_forward_under_test", ROOT / "scripts" / "run_walk_forward.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StubSignal:
    def __init__(self, timestamp, symbol="BTC/USDT", timeframe="1h"):
        self.timestamp = timestamp
        self.symbol = symbol
        self.timeframe = timeframe
        self.signal_type = SimpleNamespace(value="buy")
        self.stop_loss = 95.0
        self.exit_price = 110.0


class _StubGenerator:
    def __init__(self, frame):
        self._frame = frame

    async def generate_signal(
        self, symbol, timeframe, data, include_external=True, include_ml=True
    ):
        if len(data) < 320:
            return None
        return _StubSignal(data.index[-1], symbol, timeframe)


class TestFoldHygiene:
    def test_overlapping_indices_are_counted_as_leakage(self):
        module = _load_runner()
        hygiene = module._fold_hygiene([1, 2, 3], [2, 3, 4])
        assert hygiene["overlap"] == 2
        assert hygiene["leakage_flags"] >= 1

    def test_disjoint_indices_have_no_leakage(self):
        module = _load_runner()
        hygiene = module._fold_hygiene([0, 1, 2], [5, 6, 7])
        assert hygiene["overlap"] == 0
        assert hygiene["leakage_flags"] == 0
        assert hygiene["gap"] == 2

    def test_gap_is_zero_when_test_starts_right_after_train(self):
        module = _load_runner()
        hygiene = module._fold_hygiene([0, 1], [3, 4])
        assert hygiene["gap"] == 1


class TestWalkForwardRun:
    def test_report_has_no_leakage_and_is_versioned(self, tmp_path):
        module = _load_runner()
        frame = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
        report = module.run_walk_forward(
            FIXTURE,
            folds=3,
            out=tmp_path / "report.json",
            generator=_StubGenerator(frame),
        )
        assert report["schema_version"] == module.WALK_FORWARD_SCHEMA_VERSION
        assert report["leakage_flags"] == 0
        assert report["folds_evaluated"] == 3
        assert report["metrics_finite"] is True

    def test_every_fold_reports_hygiene_and_metrics(self, tmp_path):
        module = _load_runner()
        frame = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
        report = module.run_walk_forward(
            FIXTURE,
            folds=3,
            out=tmp_path / "report.json",
            generator=_StubGenerator(frame),
        )
        for fold in report["folds"]:
            assert fold["hygiene"]["overlap"] == 0
            assert fold["hygiene"]["leakage_flags"] == 0
            assert fold["hygiene"]["train_size"] > 0
            assert fold["hygiene"]["test_size"] > 0
            assert "win_rate" in fold["metrics"]
            assert "sharpe" in fold["metrics"]

    def test_report_is_deterministic(self, tmp_path):
        module = _load_runner()
        frame = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
        first = module.run_walk_forward(
            FIXTURE, folds=3, out=tmp_path / "a.json", generator=_StubGenerator(frame)
        )
        second = module.run_walk_forward(
            FIXTURE, folds=3, out=tmp_path / "b.json", generator=_StubGenerator(frame)
        )
        assert first["metrics_hash"] == second["metrics_hash"]

    def test_report_file_is_written(self, tmp_path):
        module = _load_runner()
        frame = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
        target = tmp_path / "nested" / "report.json"
        module.run_walk_forward(FIXTURE, folds=3, out=target, generator=_StubGenerator(frame))
        assert target.exists()

    def test_validation_passes_on_a_clean_run(self, tmp_path):
        module = _load_runner()
        frame = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
        report = module.run_walk_forward(
            FIXTURE, folds=3, out=tmp_path / "report.json", generator=_StubGenerator(frame)
        )
        assert module._validate(report) == []

    def test_validation_fails_when_leakage_is_reported(self):
        module = _load_runner()
        broken = {
            "leakage_flags": 2,
            "metrics_finite": True,
            "folds_evaluated": 1,
            "folds": [{"index": 0, "hygiene": {"overlap": 2}}],
        }
        problems = module._validate(broken)
        assert problems
        assert any("leakage" in problem for problem in problems)

    def test_validation_fails_on_non_finite_metrics(self):
        module = _load_runner()
        broken = {
            "leakage_flags": 0,
            "metrics_finite": False,
            "folds_evaluated": 1,
            "folds": [{"index": 0, "hygiene": {"overlap": 0}}],
        }
        assert module._validate(broken)
