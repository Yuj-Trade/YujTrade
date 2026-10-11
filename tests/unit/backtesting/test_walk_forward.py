"""Walk-forward folds, purge/embargo separation and the holdout guard.

Regression net for the no-leakage contract: the objective and any
validation logic must never observe test or holdout rows.
"""

import importlib.util
import statistics
from pathlib import Path

import pandas as pd
import pytest

from backtesting.walk_forward import HoldoutGuard, WalkForwardValidator
from modeling.optimization import purged_objective_score

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


class TestFoldBoundaries:
    def test_five_expanding_folds_with_min_train_fraction(self):
        data = list(range(100))
        folds = WalkForwardValidator(folds=5, min_train_fraction=0.6).split(data)
        assert len(folds) == 5
        assert [f.index for f in folds] == [0, 1, 2, 3, 4]
        boundaries = [60, 68, 76, 84, 92]
        for fold, boundary in zip(folds, boundaries, strict=False):
            assert list(fold.train) == list(range(boundary - 1))
            assert len(fold.train) >= 59
        trains = [len(f.train) for f in folds]
        assert trains == sorted(trains)

    def test_invalid_configuration_rejected(self):
        with pytest.raises(ValueError):
            WalkForwardValidator(folds=0).split(list(range(100)))
        with pytest.raises(ValueError):
            WalkForwardValidator(folds=50, min_train_fraction=0.6).split(list(range(100)))


class TestPurgeAndEmbargo:
    @pytest.mark.parametrize("warmup,sequence", [(5, 10), (10, 3), (0, 7)])
    def test_no_shared_indices_and_gap_covers_embargo(self, warmup, sequence):
        embargo = max(warmup, sequence)
        data = list(range(200))
        folds = WalkForwardValidator(
            folds=5,
            min_train_fraction=0.6,
            warmup_bars=warmup,
            sequence_length=sequence,
        ).split(data)
        assert len(folds) == 5
        for fold in folds:
            train_set = set(fold.train)
            test_list = list(fold.test)
            assert train_set.isdisjoint(test_list)
            gap = min(test_list) - max(train_set)
            assert gap >= embargo

    def test_label_horizon_purges_train_tail(self):
        data = list(range(100))
        folds = WalkForwardValidator(folds=5, min_train_fraction=0.6).split(data)
        assert list(folds[0].train)[-1] == 58
        assert list(folds[0].test)[0] == 60


class TestObjective:
    def test_median_minus_half_std(self):
        sharpes = [1.0, 2.0, 3.0]
        expected = statistics.median(sharpes) - 0.5 * statistics.pstdev(sharpes)
        assert purged_objective_score(sharpes) == pytest.approx(expected)

    def test_empty_scores_rejected(self):
        assert purged_objective_score([]) == -1.0

    def test_single_score_has_zero_spread(self):
        assert purged_objective_score([1.5]) == pytest.approx(1.5)


class TestHoldoutGuard:
    def _guard(self, tmp_path, **kwargs):
        data = list(range(100))
        return HoldoutGuard(data, holdout_fraction=0.15, state_path=tmp_path, **kwargs)

    def test_holdout_split_ratio(self, tmp_path):
        guard = self._guard(tmp_path / "state.json")
        assert len(guard.development) == 85
        assert len(guard.holdout) == 15
        assert set(guard.development).isdisjoint(guard.holdout)

    def test_consume_requires_confirmation(self, tmp_path):
        guard = self._guard(tmp_path / "state.json")
        with pytest.raises(PermissionError):
            guard.consume(confirm=False)

    def test_second_consume_without_force_rejected(self, tmp_path):
        state = tmp_path / "state.json"
        first = self._guard(state)
        assert list(first.consume(confirm=True)) == list(range(85, 100))
        second = self._guard(state)
        with pytest.raises(RuntimeError):
            second.consume(confirm=True)

    def test_force_rerun_allowed_and_recorded(self, tmp_path):
        state = tmp_path / "state.json"
        self._guard(state).consume(confirm=True)
        rerun = self._guard(state).consume(confirm=True, force_rerun=True)
        assert list(rerun) == list(range(85, 100))

    def test_invalid_fraction_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            HoldoutGuard(list(range(10)), holdout_fraction=0.0)


class TestNoLeakage:
    def test_test_rows_never_visible_in_any_train(self):
        data = list(range(300))
        folds = WalkForwardValidator(
            folds=5, min_train_fraction=0.6, warmup_bars=4, sequence_length=9
        ).split(data)
        for fold in folds:
            assert set(fold.train).isdisjoint(fold.test)
        all_test = {row for fold in folds for row in fold.test}
        assert all_test
        for fold in folds:
            assert max(fold.train) + 9 <= min(fold.test)

    def test_holdout_rows_never_in_development(self, tmp_path):
        guard = self._guard(tmp_path / "state.json")
        assert set(guard.development).isdisjoint(guard.holdout)

    def _guard(self, state_path):
        return HoldoutGuard(list(range(100)), holdout_fraction=0.15, state_path=state_path)


class TestRunHoldoutScript:
    def test_run_holdout_guards(self, tmp_path):
        module = _load_run_holdout()
        csv = _ohlcv_csv(tmp_path / "ohlcv.csv")
        state = tmp_path / "holdout_used.json"
        with pytest.raises(PermissionError):
            module.run_holdout(csv, state, confirm=False)
        result = module.run_holdout(csv, state, confirm=True)
        assert result["rows"] == 18
        assert result["data_hash"]
        assert result["config_hash"]
        assert result["start"] < result["end"]
        with pytest.raises(RuntimeError):
            module.run_holdout(csv, state, confirm=True)
        forced = module.run_holdout(csv, state, confirm=True, force_rerun=True)
        assert forced["forced"] is True
        assert forced["rows"] == 18
