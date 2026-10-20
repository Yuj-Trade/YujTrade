"""Model retraining lifecycle: drift gate, promotion guard, warm start.

These tests drive `scripts/train_models.py` through injected doubles, so the
contract is verified without training a real network or touching the network.
"""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from modeling.artifacts import ArtifactRegistry
from modeling.model_manager import TrainingOutcome

ROOT = Path(__file__).resolve().parents[3]


def _load_train_module():
    spec = importlib.util.spec_from_file_location(
        "train_models_under_test", ROOT / "scripts" / "train_models.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(name: str) -> pd.DataFrame:
    return pd.read_csv(f"tests/fixtures/{name}", index_col=0, parse_dates=True)


class _Config:
    def __init__(self, values: dict):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class _Provider:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    async def fetch_ohlcv_data(self, symbol, timeframe, limit=1000, bypass_cache=False):
        return self._frame.tail(limit)


class _ModelManager:
    def __init__(self, registry: ArtifactRegistry, outcome: TrainingOutcome | None):
        self.artifacts = registry
        self._outcome = outcome
        self.calls: list[dict] = []

    async def train_model(
        self, model_type, symbol, timeframe, data, promote=True, warm_start=False, **kwargs
    ):
        self.calls.append(
            {
                "model_type": model_type,
                "symbol": symbol,
                "timeframe": timeframe,
                "promote": promote,
                "warm_start": warm_start,
            }
        )
        return self._outcome


def _registry_with_current(tmp_path, oos_metrics: dict) -> ArtifactRegistry:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    source = tmp_path / "model.json"
    source.write_text('{"tree": 1}', encoding="utf-8")
    frame = pd.DataFrame(
        {"close": [1.0, 2.0, 3.0]},
        index=pd.date_range("2024-01-01", periods=3, tz="UTC"),
    )
    from modeling.artifacts import build_metadata

    metadata = build_metadata(
        frame, ["close"], {"max_depth": 5}, oos_metrics, source_files=[source]
    )
    registry.create_version("xgboost", "BTC/USDT", "1h", [source], metadata=metadata)
    return registry


def _registry_with_candidate(
    tmp_path, baseline_metrics: dict, candidate_metrics: dict, version: str
) -> ArtifactRegistry:
    registry = _registry_with_current(tmp_path, baseline_metrics)
    source = tmp_path / "candidate.json"
    source.write_text('{"tree": 2}', encoding="utf-8")
    frame = pd.DataFrame(
        {"close": [4.0, 5.0, 6.0]},
        index=pd.date_range("2024-02-01", periods=3, tz="UTC"),
    )
    from modeling.artifacts import build_metadata

    metadata = build_metadata(
        frame, ["close"], {"max_depth": 6}, candidate_metrics, source_files=[source]
    )
    registry.create_version(
        "xgboost",
        "BTC/USDT",
        "1h",
        [source],
        metadata=metadata,
        version=version,
        update_current=False,
    )
    return registry


def _trainer(tmp_path, frame, outcome, config_values=None):
    module = _load_train_module()
    values = {
        "drift_alpha": 0.05,
        "drift_min_window": 100,
        "drift_live_window": 300,
        "drift_live_windows": {"1h": 600},
        "promotion_max_directional_accuracy_drop": 0.10,
        "promotion_max_rmse_increase_ratio": 1.25,
    }
    values.update(config_values or {})
    registry = ArtifactRegistry(tmp_path / "artifacts")
    manager = _ModelManager(registry, outcome)
    trainer = module.ModelTrainer(
        _Config(values), _Provider(frame), manager, warm_start=False, rollback_guard=True
    )
    return module, trainer, manager, registry


class TestDriftGate:
    async def test_dry_run_reports_drift_without_training(self, tmp_path):
        module, trainer, manager, _ = _trainer(tmp_path, _fixture("drift_shifted_1h.csv"), None)
        entry = await trainer.dry_run("BTC/USDT", "1h")
        assert entry["status"] == "drift"
        assert entry["drift"]["drifted"] is True
        assert manager.calls == []

    async def test_dry_run_on_stationary_data_is_stable(self, tmp_path):
        module, trainer, manager, _ = _trainer(tmp_path, _fixture("drift_stable_1h.csv"), None)
        entry = await trainer.dry_run("BTC/USDT", "1h")
        assert entry["status"] == "stable"
        assert entry["drift"]["drifted"] is False
        assert manager.calls == []

    async def test_drift_summary_is_attached_to_training_entries(self, tmp_path):
        outcome = TrainingOutcome(
            model_type="xgboost",
            symbol="BTC/USDT",
            timeframe="1h",
            version="v1",
            promoted=False,
            oos_metrics={"rmse": 1.0, "directional_accuracy": 0.7},
            artifact_path="artifacts/x",
        )
        module, trainer, _, _ = _trainer(tmp_path, _fixture("drift_shifted_1h.csv"), outcome)
        entry = await trainer.train_and_save_model("BTC/USDT", "1h", "xgboost")
        assert entry["drift"]["drifted"] is True
        assert entry["drift"]["schema_version"] == 1


class TestPromotionGuard:
    async def test_healthy_candidate_updates_the_pointer(self, tmp_path):
        outcome = TrainingOutcome(
            model_type="xgboost",
            symbol="BTC/USDT",
            timeframe="1h",
            version="v2",
            promoted=False,
            oos_metrics={"rmse": 9.0, "directional_accuracy": 0.62},
            artifact_path="artifacts/x",
        )
        registry = _registry_with_candidate(
            tmp_path,
            {"rmse": 10.0, "directional_accuracy": 0.60},
            {"rmse": 9.0, "directional_accuracy": 0.62},
            "v2",
        )
        module = _load_train_module()
        manager = _ModelManager(registry, outcome)
        trainer = module.ModelTrainer(
            _Config({"drift_alpha": 0.05, "drift_min_window": 100}),
            _Provider(_fixture("drift_stable_1h.csv")),
            manager,
        )
        entry = await trainer.train_and_save_model("BTC/USDT", "1h", "xgboost")
        assert entry["promoted"] is True
        assert entry["status"] == "promoted"
        assert registry.current_version("xgboost", "BTC/USDT", "1h") == "v2"
        assert manager.calls[0]["promote"] is False

    async def test_degraded_candidate_keeps_the_previous_pointer(self, tmp_path):
        outcome = TrainingOutcome(
            model_type="xgboost",
            symbol="BTC/USDT",
            timeframe="1h",
            version="v2",
            promoted=False,
            oos_metrics={"rmse": 9.0, "directional_accuracy": 0.20},
            artifact_path="artifacts/x",
        )
        registry = _registry_with_candidate(
            tmp_path,
            {"rmse": 10.0, "directional_accuracy": 0.80},
            {"rmse": 9.0, "directional_accuracy": 0.20},
            "v2",
        )
        previous = registry.current_version("xgboost", "BTC/USDT", "1h")
        module = _load_train_module()
        manager = _ModelManager(registry, outcome)
        trainer = module.ModelTrainer(
            _Config({"drift_alpha": 0.05, "drift_min_window": 100}),
            _Provider(_fixture("drift_stable_1h.csv")),
            manager,
        )
        entry = await trainer.train_and_save_model("BTC/USDT", "1h", "xgboost")
        assert entry["promoted"] is False
        assert entry["status"] == "rejected"
        assert registry.current_version("xgboost", "BTC/USDT", "1h") == previous
        assert "v2" in registry.list_versions("xgboost", "BTC/USDT", "1h")

    async def test_training_never_promotes_before_the_guard_runs(self, tmp_path):
        outcome = TrainingOutcome(
            model_type="xgboost",
            symbol="BTC/USDT",
            timeframe="1h",
            version="v2",
            promoted=False,
            oos_metrics={"rmse": 1.0, "directional_accuracy": 0.9},
            artifact_path="artifacts/x",
        )
        module, trainer, manager, _ = _trainer(tmp_path, _fixture("drift_stable_1h.csv"), outcome)
        await trainer.train_and_save_model("BTC/USDT", "1h", "xgboost")
        assert manager.calls[0]["promote"] is False


class TestTrainingReport:
    async def test_entry_reports_version_and_decision(self, tmp_path):
        outcome = TrainingOutcome(
            model_type="xgboost",
            symbol="BTC/USDT",
            timeframe="1h",
            version="v3",
            promoted=False,
            oos_metrics={"rmse": 9.0, "directional_accuracy": 0.62},
            artifact_path="artifacts/x",
        )
        module, trainer, _, _ = _trainer(tmp_path, _fixture("drift_stable_1h.csv"), outcome)
        entry = await trainer.train_and_save_model("BTC/USDT", "1h", "xgboost")
        assert entry["version"] == "v3"
        assert entry["decision"]["promote"] is True
        assert entry["decision"]["schema_version"] == 1
        json.dumps(entry)

    async def test_insufficient_data_is_reported_not_raised(self, tmp_path):
        module, trainer, manager, _ = _trainer(
            tmp_path, _fixture("drift_stable_1h.csv").head(50), None
        )
        entry = await trainer.train_and_save_model("BTC/USDT", "1h", "xgboost")
        assert entry["status"] == "skipped"
        assert entry["reason"] == "insufficient_data"
        assert manager.calls == []


class TestCliSurface:
    def test_parser_exposes_the_documented_flags(self):
        module = _load_train_module()
        parser = module._build_parser()
        args = parser.parse_args(
            [
                "--dry-run",
                "--warm-start",
                "--data",
                "fixture.csv",
                "--symbol",
                "BTC/USDT",
                "--timeframe",
                "1h",
                "--only-on-drift",
                "--report",
                "report.json",
            ]
        )
        assert args.dry_run is True
        assert args.warm_start is True
        assert str(args.data) == "fixture.csv"
        assert args.only_on_drift is True
        assert str(args.report) == "report.json"

    def test_drift_check_exit_code_is_declared(self):
        module = _load_train_module()
        assert module.DRIFT_CHECK_ONLY_EXIT_CODE == 2

    def test_csv_fixture_loader_validates_columns(self, tmp_path):
        module = _load_train_module()
        broken = tmp_path / "broken.csv"
        broken.write_text("timestamp,close\n2025-01-01,1.0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing columns"):
            module.load_csv_ohlcv(broken)

    def test_csv_fixture_loader_reads_a_valid_frame(self, tmp_path):
        module = _load_train_module()
        frame = module.load_csv_ohlcv("tests/fixtures/drift_stable_1h.csv")
        assert len(frame) == 1200
        assert {"open", "high", "low", "close", "volume"} <= set(frame.columns)
