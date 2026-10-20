"""Versioned Monte-Carlo block in the holdout report.

The block is the diffable artifact of distributional robustness: same trades,
same seed, same interval, so a regression between two runs is visible.
"""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from backtesting.montecarlo import (
    MONTE_CARLO_SCHEMA_VERSION,
    bootstrap_confidence_interval,
    simulate_r_multiples,
)

ROOT = Path(__file__).resolve().parents[3]


def _load_run_holdout():
    spec = importlib.util.spec_from_file_location(
        "run_holdout_under_test", ROOT / "scripts" / "run_holdout.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ohlcv_csv(path: Path, rows: int = 120) -> Path:
    index = pd.date_range("2024-01-01", periods=rows, freq="1h")
    frame = pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1000.0] * rows,
        },
        index=index,
    )
    path.write_text(frame.to_csv(), encoding="utf-8")
    return path


class TestBootstrapInterval:
    def test_block_carries_a_version_and_the_confidence_level(self):
        block = bootstrap_confidence_interval([1.0, -0.5, 2.0, 0.25])
        assert block["schema_version"] == MONTE_CARLO_SCHEMA_VERSION
        assert block["confidence"] == pytest.approx(0.95)
        assert block["simulations"] == 1000
        assert block["seed"] == 42

    def test_interval_brackets_the_sample_mean(self):
        block = bootstrap_confidence_interval([1.0, -0.5, 2.0, 0.25])
        assert block["ci_low"] <= block["mean"] <= block["ci_high"]

    def test_same_seed_produces_the_same_block(self):
        first = bootstrap_confidence_interval([1.0, -0.5, 2.0])
        second = bootstrap_confidence_interval([1.0, -0.5, 2.0])
        assert first == second

    def test_different_seed_is_reproducible_but_distinct(self):
        first = bootstrap_confidence_interval([1.0, -0.5, 2.0], seed=1)
        second = bootstrap_confidence_interval([1.0, -0.5, 2.0], seed=2)
        assert first["seed"] == 1
        assert second["seed"] == 2
        assert first == bootstrap_confidence_interval([1.0, -0.5, 2.0], seed=1)

    def test_empty_trade_set_produces_a_zero_width_interval(self):
        block = bootstrap_confidence_interval([])
        assert block["samples"] == 0
        assert block["ci_low"] == 0.0
        assert block["ci_high"] == 0.0

    def test_block_is_json_serializable(self):
        import json

        json.dumps(bootstrap_confidence_interval([1.0, 2.0]))


class TestMonteCarloSimulation:
    def test_simulation_is_deterministic_for_a_fixed_seed(self):
        first = simulate_r_multiples([1.0, -1.0, 2.0], simulations=50, seed=7)
        second = simulate_r_multiples([1.0, -1.0, 2.0], simulations=50, seed=7)
        assert first == second

    def test_empty_input_produces_no_simulations(self):
        assert simulate_r_multiples([], simulations=10) == []


class TestHoldoutReport:
    def test_report_contains_the_versioned_monte_carlo_block(self, tmp_path):
        module = _load_run_holdout()
        csv = _ohlcv_csv(tmp_path / "ohlcv.csv")
        report = module.run_holdout(
            csv,
            tmp_path / "holdout_used.json",
            confirm=True,
            out=tmp_path / "report.json",
        )
        block = report["monte_carlo"]
        assert block["schema_version"] == MONTE_CARLO_SCHEMA_VERSION
        assert block["confidence"] == pytest.approx(0.95)
        assert "ci_low" in block and "ci_high" in block

    def test_legacy_bootstrap_field_is_preserved(self, tmp_path):
        module = _load_run_holdout()
        csv = _ohlcv_csv(tmp_path / "ohlcv.csv")
        report = module.run_holdout(
            csv,
            tmp_path / "holdout_used.json",
            confirm=True,
            out=tmp_path / "report.json",
        )
        assert len(report["bootstrap_ci_95"]) == 2

    def test_report_is_byte_deterministic(self, tmp_path):
        module = _load_run_holdout()
        csv = _ohlcv_csv(tmp_path / "ohlcv.csv")
        state = tmp_path / "holdout_used.json"
        first = module.run_holdout(csv, state, confirm=True, out=tmp_path / "a.json")
        second = module.run_holdout(
            csv, state, confirm=True, force_rerun=True, out=tmp_path / "b.json"
        )
        assert first["monte_carlo"] == second["monte_carlo"]
