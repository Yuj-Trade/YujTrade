import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from common.exceptions import ArtifactIntegrityError
from modeling.artifacts import (
    REQUIRED_METADATA_KEYS,
    ArtifactRegistry,
    build_metadata,
)
from modeling.model_manager import ModelManager, compute_oos_metrics


def _frame(rows=8):
    return pd.DataFrame(
        {"close": [float(100 + i) for i in range(rows)]},
        index=pd.date_range("2024-01-01", periods=rows, tz="UTC"),
    )


def _metadata(source, source_files=None, **overrides):
    payload = build_metadata(
        _frame(), ["close"], {"p": 1}, {}, source_files=source_files or [source]
    )
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("key", list(REQUIRED_METADATA_KEYS))
def test_create_version_rejects_missing_required_key(tmp_path, key):
    registry = ArtifactRegistry(tmp_path / "artifacts")
    source = tmp_path / "model.json"
    source.write_text("{}", encoding="utf-8")
    metadata = _metadata(source)
    metadata.pop(key)
    with pytest.raises(ValueError, match="missing required keys"):
        registry.create_version("xgboost", "BTC/USDT", "1h", [source], metadata=metadata)


def test_create_version_rejects_empty_required_values(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts")
    source = tmp_path / "model.json"
    source.write_text("{}", encoding="utf-8")
    metadata = _metadata(source, feature_list=[], git_commit="")
    with pytest.raises(ValueError, match="missing required keys"):
        registry.create_version("xgboost", "BTC/USDT", "1h", [source], metadata=metadata)


def test_create_version_rejects_none_metadata(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="missing required keys"):
        registry.create_version("xgboost", "BTC/USDT", "1h", [], metadata=None)


def test_verify_current_accepts_untampered_artifact(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts")
    source = tmp_path / "model.json"
    source.write_text('{"tree": 1}', encoding="utf-8")
    version_dir = registry.create_version(
        "xgboost", "BTC/USDT", "1h", [source], metadata=_metadata(source)
    )
    assert registry.verify_current("xgboost", "BTC/USDT", "1h") == version_dir


def test_verify_current_rejects_tampered_model_file(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts")
    source = tmp_path / "model.json"
    source.write_text('{"tree": 1}', encoding="utf-8")
    registry.create_version("xgboost", "BTC/USDT", "1h", [source], metadata=_metadata(source))
    directory = registry.current_dir("xgboost", "BTC/USDT", "1h")
    (directory / "model.json").write_text('{"tree": 999}', encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError):
        registry.verify_current("xgboost", "BTC/USDT", "1h")


def test_verify_current_rejects_legacy_artifact_without_hashes(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts")
    model_root = registry.model_dir("xgboost", "BTC/USDT", "1h")
    version_dir = model_root / "v1"
    version_dir.mkdir(parents=True)
    (version_dir / "metadata.json").write_text(json.dumps({"version": "v1"}), encoding="utf-8")
    (model_root / "current.json").write_text(json.dumps({"version": "v1"}), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError):
        registry.verify_current("xgboost", "BTC/USDT", "1h")


def test_tampered_artifact_predict_returns_none(tmp_path):
    registry = ArtifactRegistry(tmp_path / "artifacts")
    model_file = tmp_path / "xgboost_btcusdt_1h.json"
    scaler_file = tmp_path / "scaler_xgboost_btcusdt_1h.pkl"
    model_file.write_text('{"tree": 1}', encoding="utf-8")
    scaler_file.write_bytes(b"scaler-bytes")
    registry.create_version(
        "xgboost",
        "BTC/USDT",
        "1h",
        [model_file, scaler_file],
        metadata=_metadata(model_file, source_files=[model_file, scaler_file]),
    )
    directory = registry.current_dir("xgboost", "BTC/USDT", "1h")
    (directory / model_file.name).write_text('{"tree": 999}', encoding="utf-8")

    data_provider = MagicMock(name="ModelDataProvider")
    data_provider.get_data_for_model = AsyncMock()
    manager = ModelManager(
        data_provider,
        model_path=str(tmp_path / "models"),
        auto_train_on_predict=False,
    )
    manager.artifacts = registry
    result = asyncio.run(manager.predict_with_confidence("xgboost", "BTC/USDT", "1h"))
    assert result is None
    data_provider.get_data_for_model.assert_not_called()


def test_build_metadata_without_git_reports_unknown(tmp_path, monkeypatch):
    import hashlib

    import modeling.artifacts as artifacts_module

    def _boom(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(artifacts_module.subprocess, "run", _boom)
    source = tmp_path / "model.json"
    source.write_text("{}", encoding="utf-8")
    payload = build_metadata(_frame(), ["close"], {"p": 1}, {}, source_files=[source])
    assert payload["git_commit"] == "unknown"
    assert payload["data_start"] == "2024-01-01T00:00:00+00:00"
    assert payload["files_sha256"] == {"model.json": hashlib.sha256(b"{}").hexdigest()}


def test_compute_oos_metrics_reports_rmse_and_directional_accuracy():
    class _Model:
        def predict(self, data):
            import numpy as np

            last = float(data["close"].iloc[-1])
            return np.array([last + 1.0]), 0.1

    metrics = compute_oos_metrics(_Model(), _frame(rows=20))
    assert set(metrics) == {"rmse", "directional_accuracy"}
    assert metrics["rmse"] == pytest.approx(0.0)
    assert metrics["directional_accuracy"] == pytest.approx(1.0)


def test_oos_metrics_purge_skips_boundary_row():
    seen = []

    class _Model:
        def predict(self, data):
            import numpy as np

            seen.append(len(data))
            return np.array([float(data["close"].iloc[-1])]), 0.0

    compute_oos_metrics(_Model(), _frame(rows=20))
    assert seen == [18, 19]
