"""Training must never mutate a promoted artifact.

The promotion guard is only meaningful if a rejected candidate leaves the
promoted version byte-identical. These tests drive the real `ModelManager`
with a fake model object so the write path is exercised without a network
or a real estimator.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from modeling.artifacts import ArtifactRegistry
from modeling.model_manager import ModelManager

SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"


class _FakeScaler:
    def __init__(self):
        self.scale_ = np.array([1.0, 2.0])
        self.n_features_in_ = 2
        self.feature_columns = ["close", "volume"]


class _FakeFeatureEngineer:
    def __init__(self):
        self.scaler = _FakeScaler()

    def create_features(self, data):
        return pd.DataFrame(
            {
                "close": data["close"].to_numpy(dtype=float),
                "volume": data["volume"].to_numpy(dtype=float),
            },
            index=data.index,
        )

    def get_typical_volatility(self, timeframe):
        return 0.01


class _FakeModel:
    def __init__(self, model_path: Path):
        self.model_path = Path(model_path)
        self.feature_engineer = _FakeFeatureEngineer()
        self.is_trained = False
        self._is_closed = False
        self.params = {"max_depth": 5}
        self.written: dict[str, bytes] = {}

    def _get_model_paths(self, model_name, extension):
        safe = SYMBOL.lower().replace("/", "")
        base = self.model_path / f"{model_name}_{safe}_{TIMEFRAME}"
        scaler = self.model_path / f"scaler_{model_name}_{safe}_{TIMEFRAME}.json"
        return base.with_suffix(f".{extension}"), scaler

    def fit(self, data, warm_start=False, **kwargs):
        model_file, scaler_file = self._get_model_paths("xgboost", "json")
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_text('{"tree": 2}', encoding="utf-8")
        scaler_file.write_text(json.dumps({"scale_": [1.0, 2.0]}), encoding="utf-8")
        self.written["model"] = model_file.read_bytes()
        self.written["scaler"] = scaler_file.read_bytes()
        self.is_trained = True
        return True

    def predict(self, data):
        close = float(data["close"].iloc[-1])
        return np.array([close * 1.01]), 0.1

    def cleanup(self):
        self._is_closed = True


def _frame(rows: int = 120) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="1h", tz="UTC")
    close = np.linspace(100.0, 130.0, rows)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(rows, 1000.0),
        },
        index=index,
    )


class _Provider:
    async def get_data_for_model(self, symbol, timeframe, for_prediction=False):
        return _frame()


async def _manager(tmp_path, model) -> ModelManager:
    manager = ModelManager(data_provider=_Provider(), model_path=str(tmp_path / "models"))
    manager.artifacts = ArtifactRegistry(tmp_path / "artifacts")
    model.model_path = tmp_path / "models" / "xgboost"

    async def _get_model(model_type, symbol, timeframe, auto_load=True):
        return model

    manager.get_model = _get_model
    return manager


class TestArtifactImmutabilityDuringTraining:
    async def test_training_never_writes_into_the_promoted_version(self, tmp_path):
        manager = await _manager(tmp_path, _FakeModel(tmp_path / "models" / "xgboost"))
        outcome = await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame(), promote=False)
        assert outcome is not None
        assert manager.artifacts.current_dir("xgboost", SYMBOL, TIMEFRAME) is None
        version_dir = manager.artifacts.version_dir("xgboost", SYMBOL, TIMEFRAME, outcome.version)
        assert (version_dir / "xgboost_btcusdt_1h.json").exists()
        metadata = json.loads((version_dir / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["files_sha256"]

    async def test_promoted_artifact_stays_verifiable_after_a_rejected_candidate(self, tmp_path):
        manager = await _manager(tmp_path, _FakeModel(tmp_path / "models" / "xgboost"))
        first = await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame(), promote=True)
        assert first is not None
        promoted = manager.artifacts.current_dir("xgboost", SYMBOL, TIMEFRAME)
        before = (promoted / "xgboost_btcusdt_1h.json").read_bytes()

        second = await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame(), promote=False)
        assert second is not None
        after = (promoted / "xgboost_btcusdt_1h.json").read_bytes()
        assert before == after
        assert manager.artifacts.verify_current("xgboost", SYMBOL, TIMEFRAME) is not None

    async def test_a_rejected_candidate_is_not_cached_for_prediction(self, tmp_path):
        manager = await _manager(tmp_path, _FakeModel(tmp_path / "models" / "xgboost"))
        await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame(), promote=True)
        assert "xgboost-BTC/USDT-1h" in manager._cache
        await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame(), promote=False)
        assert "xgboost-BTC/USDT-1h" not in manager._cache

    async def test_the_staging_path_is_used_for_writes(self, tmp_path):
        model = _FakeModel(tmp_path / "models" / "xgboost")
        manager = await _manager(tmp_path, model)
        outcome = await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame(), promote=False)
        assert model.written
        staging_file = tmp_path / "models" / "xgboost" / "xgboost_btcusdt_1h.json"
        assert staging_file.exists()
        version_file = (
            manager.artifacts.version_dir("xgboost", SYMBOL, TIMEFRAME, outcome.version)
            / "xgboost_btcusdt_1h.json"
        )
        assert version_file.read_bytes() == staging_file.read_bytes()

    async def test_the_promoted_version_is_not_rewritten_in_place(self, tmp_path):
        model = _FakeModel(tmp_path / "models" / "xgboost")
        manager = await _manager(tmp_path, model)
        await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame(), promote=True)
        promoted = manager.artifacts.current_dir("xgboost", SYMBOL, TIMEFRAME)
        recorded = json.loads((promoted / "metadata.json").read_text(encoding="utf-8"))
        digest = recorded["files_sha256"]["xgboost_btcusdt_1h.json"]
        actual = hashlib.sha256((promoted / "xgboost_btcusdt_1h.json").read_bytes()).hexdigest()
        assert digest == actual


class TestTrainingOutcome:
    async def test_outcome_carries_version_and_metrics(self, tmp_path):
        manager = await _manager(tmp_path, _FakeModel(tmp_path / "models" / "xgboost"))
        outcome = await manager.train_model("xgboost", SYMBOL, TIMEFRAME, _frame())
        assert outcome is not None
        assert outcome.model_type == "xgboost"
        assert outcome.version
        assert "rmse" in outcome.oos_metrics
        assert outcome.promoted is True
        assert Path(outcome.artifact_path).exists()

    async def test_empty_data_returns_no_outcome(self, tmp_path):
        manager = await _manager(tmp_path, _FakeModel(tmp_path / "models" / "xgboost"))
        outcome = await manager.train_model(
            "xgboost", SYMBOL, TIMEFRAME, pd.DataFrame(), promote=False
        )
        assert outcome is None
