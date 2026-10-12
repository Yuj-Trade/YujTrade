import numpy as np
import pytest
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

from modeling.scaler_io import (
    dump_scaler,
    load_scaler,
    scaler_from_dict,
    scaler_to_dict,
)

SCALERS = [
    StandardScaler(),
    MinMaxScaler(),
    RobustScaler(),
]


def _fitted(scaler):
    data = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0], [4.0, 40.0]])
    return scaler.fit(data)


@pytest.mark.parametrize("scaler", SCALERS, ids=["standard", "minmax", "robust"])
def test_scaler_round_trip_preserves_transform(scaler):
    fitted = _fitted(scaler)
    sample = np.array([[2.5, 15.0], [3.5, 35.0]])
    expected = fitted.transform(sample)
    restored = scaler_from_dict(scaler_to_dict(fitted))
    np.testing.assert_array_equal(restored.transform(sample), expected)


@pytest.mark.parametrize("scaler", SCALERS, ids=["standard", "minmax", "robust"])
def test_scaler_json_file_round_trip(tmp_path, scaler):
    fitted = _fitted(scaler)
    sample = np.array([[2.5, 15.0]])
    expected = fitted.transform(sample)
    path = tmp_path / "scaler.json"
    dump_scaler(path, fitted)
    np.testing.assert_array_equal(load_scaler(path).transform(sample), expected)


def test_unknown_scaler_type_raises_type_error():
    with pytest.raises(TypeError):
        scaler_to_dict(object())
    with pytest.raises(TypeError):
        scaler_from_dict({"type": "Nope", "params": {}, "attributes": {}})


def test_legacy_pkl_only_means_model_unavailable(tmp_path):
    from modeling.models import XGBoostModel

    model = XGBoostModel(symbol="BTC/USDT", timeframe="1h", model_path=str(tmp_path / "m"))
    _, scaler_file = model._get_model_paths("xgboost", "json")
    scaler_file.parent.mkdir(parents=True, exist_ok=True)
    scaler_file.with_suffix(".pkl").write_bytes(b"legacy-pickle-bytes")
    assert model.load_scaler("xgboost") is False
