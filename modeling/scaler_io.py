import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

_SCALER_TYPES = {
    "StandardScaler": StandardScaler,
    "MinMaxScaler": MinMaxScaler,
    "RobustScaler": RobustScaler,
}

_STANDARD_ATTRS = ("mean_", "scale_", "var_", "n_features_in_", "n_samples_seen_")
_MINMAX_ATTRS = (
    "data_min_",
    "data_max_",
    "scale_",
    "min_",
    "data_range_",
    "n_features_in_",
    "n_samples_seen_",
)
_ROBUST_ATTRS = ("center_", "scale_", "n_features_in_")

_ATTRS_BY_TYPE = {
    "StandardScaler": _STANDARD_ATTRS,
    "MinMaxScaler": _MINMAX_ATTRS,
    "RobustScaler": _ROBUST_ATTRS,
}


def _freeze(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return {"__ndarray__": True, "dtype": str(value.dtype), "data": value.tolist()}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, tuple):
        return {"__tuple__": True, "data": [_freeze(item) for item in value]}
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__ndarray__"):
        return np.asarray(value["data"], dtype=value["dtype"])
    if isinstance(value, dict) and value.get("__tuple__"):
        return tuple(_thaw(item) for item in value["data"])
    return value


def scaler_to_dict(scaler: Any) -> dict[str, Any]:
    scaler_type = type(scaler).__name__
    if scaler_type not in _SCALER_TYPES:
        raise TypeError(f"Unsupported scaler type: {scaler_type}")
    attributes: dict[str, Any] = {}
    for name in _ATTRS_BY_TYPE[scaler_type]:
        if not hasattr(scaler, name):
            raise ValueError(f"Scaler {scaler_type} is not fitted (missing {name})")
        attributes[name] = _freeze(getattr(scaler, name))
    params = {key: _freeze(val) for key, val in scaler.get_params().items()}
    return {"type": scaler_type, "params": params, "attributes": attributes}


def scaler_from_dict(payload: dict[str, Any]) -> Any:
    scaler_type = payload.get("type")
    if scaler_type not in _SCALER_TYPES:
        raise TypeError(f"Unsupported scaler type: {scaler_type}")
    scaler = _SCALER_TYPES[scaler_type](
        **{key: _thaw(val) for key, val in payload.get("params", {}).items()}
    )
    for name in _ATTRS_BY_TYPE[scaler_type]:
        setattr(scaler, name, _thaw(payload["attributes"][name]))
    return scaler


def dump_scaler(path: str | Path, scaler: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(scaler_to_dict(scaler), sort_keys=True), encoding="utf-8")
    return target


def load_scaler(path: str | Path) -> Any:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return scaler_from_dict(payload)
