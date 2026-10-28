import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_run_walk_forward():
    spec = importlib.util.spec_from_file_location(
        "run_walk_forward", ROOT / "scripts/run_walk_forward.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_csv(path: Path, rows: int = 120) -> Path:
    dates = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
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


@pytest.fixture
def stub_generator():
    generator = MagicMock()
    generator.generate_signal = AsyncMock(return_value=None)
    return generator


def test_run_walk_forward_report_structure(tmp_path, stub_generator):
    module = load_run_walk_forward()
    csv = make_csv(tmp_path / "ohlcv.csv")
    report = module.run_walk_forward(
        csv,
        symbol="BTC/USDT",
        timeframe="1h",
        folds=2,
        min_train_fraction=0.5,
        out=tmp_path / "wf.json",
        generator=stub_generator,
    )
    assert report["schema_version"] == module.WALK_FORWARD_SCHEMA_VERSION
    assert report["folds_requested"] == 2
    assert report["folds_evaluated"] > 0
    assert report["leakage_flags"] == 0
    assert report["metrics_finite"] is True
    assert report["data_hash"] == report["data_hash"]
    assert len(report["data_hash"]) != 0
    assert report["signals_total"] == 0
    assert (tmp_path / "wf.json").exists()


def test_run_walk_forward_validate_reports_no_problems(tmp_path, stub_generator):
    module = load_run_walk_forward()
    csv = make_csv(tmp_path / "ohlcv.csv")
    report = module.run_walk_forward(
        csv, folds=3, min_train_fraction=0.5, out=tmp_path / "wf.json", generator=stub_generator
    )
    assert module._validate(report) == []


def test_run_walk_forward_fold_hygiene_no_overlap(tmp_path, stub_generator):
    module = load_run_walk_forward()
    csv = make_csv(tmp_path / "ohlcv.csv")
    report = module.run_walk_forward(
        csv, folds=4, min_train_fraction=0.6, out=tmp_path / "wf.json", generator=stub_generator
    )
    for fold in report["folds"]:
        assert fold["hygiene"]["overlap"] == 0
        assert fold["hygiene"]["leakage_flags"] == 0
    assert report["leakage_flags"] == 0


def test_run_walk_forward_default_output_path_is_git_ignored(tmp_path, stub_generator, monkeypatch):
    module = load_run_walk_forward()
    monkeypatch.chdir(tmp_path)
    csv = make_csv(tmp_path / "ohlcv.csv")
    report = module.run_walk_forward(csv, generator=stub_generator)
    report_path = Path(report["report_path"])
    assert report_path.exists()
    assert report_path.parent.parent.name == "runs"


def test_finite_helper():
    module = load_run_walk_forward()
    assert module._finite(1.0) is True
    assert module._finite(float("nan")) is False
    assert module._finite(float("inf")) is False


def test_fold_hygiene_detects_leakage():
    module = load_run_walk_forward()
    hygiene = module._fold_hygiene([0, 1, 2], [2, 3, 4])
    assert hygiene["overlap"] == 1
    assert hygiene["leakage_flags"] >= 2
    assert hygiene["gap"] == -1


def test_fold_hygiene_clean_splits():
    module = load_run_walk_forward()
    hygiene = module._fold_hygiene([0, 1, 2], [5, 6])
    assert hygiene["overlap"] == 0
    assert hygiene["leakage_flags"] == 0
    assert hygiene["gap"] == 2
