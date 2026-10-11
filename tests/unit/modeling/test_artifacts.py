"""ML artifact lifecycle: metadata round-trip, per-model calibration keys,
no-autotrain predict contract and the XGBoost next-close label with purge.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd

from modeling.artifacts import ArtifactRegistry
from modeling.model_manager import ModelManager
from modeling.models import XGBoostModel

METADATA_FIELDS = {
    "version",
    "trained_at_utc",
    "data_start",
    "data_end",
    "data_sha256",
    "feature_list",
    "params",
    "oos_metrics",
    "git_commit",
    "library_versions",
}


def _registry(tmp_path) -> ArtifactRegistry:
    return ArtifactRegistry(tmp_path / "artifacts")


def test_metadata_round_trip_covers_all_fields(tmp_path):
    registry = _registry(tmp_path)
    source = tmp_path / "model.json"
    source.write_text('{"tree": 1}', encoding="utf-8")
    overrides = {
        "data_start": "2024-01-01T00:00:00+00:00",
        "data_end": "2024-02-01T00:00:00+00:00",
        "feature_list": ["close", "volume"],
        "params": {"max_depth": 5},
        "oos_metrics": {"sharpe": 1.2},
        "git_commit": "abc123",
        "library_versions": {"xgboost": "3.4.1"},
    }
    version_dir = registry.create_version("xgboost", "BTC/USDT", "1h", [source], metadata=overrides)
    payload = json.loads((version_dir / "metadata.json").read_text(encoding="utf-8"))
    assert METADATA_FIELDS <= set(payload)
    for key, value in overrides.items():
        assert payload[key] == value
    assert payload["data_sha256"]
    assert (version_dir / "model.json").exists()


def test_missing_current_pointer_means_no_artifact(tmp_path):
    registry = _registry(tmp_path)
    assert registry.current_dir("xgboost", "BTC/USDT", "1h") is None
    assert registry.load_calibration("xgboost", "BTC/USDT", "1h") == []


def test_calibration_keys_are_independent_per_model(tmp_path):
    registry = _registry(tmp_path)
    for model_type in ("lstm", "xgboost"):
        registry.create_version(model_type, "BTC/USDT", "1h", [])
    registry.save_calibration("lstm", "BTC/USDT", "1h", [(0.8, True, 1.0)])
    registry.save_calibration("xgboost", "BTC/USDT", "1h", [(0.6, False, 2.0), (0.9, True, 1.0)])
    assert registry.load_calibration("lstm", "BTC/USDT", "1h") == [(0.8, True, 1.0)]
    assert registry.load_calibration("xgboost", "BTC/USDT", "1h") == [
        (0.6, False, 2.0),
        (0.9, True, 1.0),
    ]


def test_predict_untrained_model_returns_none_without_data_fetch(tmp_path):
    data_provider = MagicMock(name="ModelDataProvider")
    data_provider.get_data_for_model = AsyncMock()
    manager = ModelManager(
        data_provider,
        model_path=str(tmp_path / "models"),
        auto_train_on_predict=False,
    )
    stub = SimpleNamespace(is_trained=False)
    manager.get_model = AsyncMock(return_value=stub)

    result = asyncio.run(manager.predict_with_confidence("xgboost", "BTC/USDT", "1h"))

    assert result is None
    data_provider.get_data_for_model.assert_not_called()


def test_xgboost_label_is_next_close_with_last_row_purged(tmp_path, monkeypatch):
    model = XGBoostModel(symbol="BTCUSDT", timeframe="1h", model_path=str(tmp_path / "m"))
    closes = [float(100 + i) for i in range(60)]
    frame = pd.DataFrame({"close": closes, "volume": [1.0] * 60})
    monkeypatch.setattr(model.feature_engineer, "create_features", lambda data: frame)
    monkeypatch.setattr(
        model.feature_engineer, "scale_features", lambda features, fit=True: features.values
    )
    captured = {}

    class _FakeRegressor:
        def fit(self, x, y, **kwargs):
            captured["x"] = np.asarray(x)
            captured["y"] = np.asarray(y)
            return self

    monkeypatch.setattr(model, "model", _FakeRegressor())
    monkeypatch.setattr(model, "save", lambda: None)

    assert model.fit(pd.DataFrame({"close": closes})) is True
    # 60 rows -> shift(-1).dropna() purges the last row (no next close) -> 59;
    # the 80/20 split of 59 yields 47 train rows (80% of 60 would be 48).
    assert len(captured["y"]) == 47
    assert len(captured["x"]) == 47
    assert list(captured["y"]) == closes[1 : 1 + 47]
    assert closes[-1] not in list(captured["y"])
