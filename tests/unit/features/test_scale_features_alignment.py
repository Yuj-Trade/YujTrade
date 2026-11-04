import numpy as np
import pandas as pd

from features.feature_engineering import FeatureEngineer


def _frame(columns: list[str], rows: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    return pd.DataFrame(
        {name: rng.random(rows) for name in columns},
        index=pd.date_range("2024-01-01", periods=rows, freq="h"),
    )


def _expected_minmax(frame: pd.DataFrame, name: str) -> np.ndarray:
    column = frame[name]
    span = column.max() - column.min()
    return ((column - column.min()) / span).to_numpy()


def test_transform_reorders_columns_to_the_fit_time_order():
    engineer = FeatureEngineer()
    fit_frame = _frame(["a", "b", "c"])
    engineer.scale_features(fit_frame, fit=True)

    scaled = engineer.scale_features(fit_frame[["c", "a", "b"]], fit=False)

    assert scaled is not None
    np.testing.assert_allclose(scaled[:, 0], _expected_minmax(fit_frame, "a"))
    np.testing.assert_allclose(scaled[:, 1], _expected_minmax(fit_frame, "b"))


def test_transform_skips_when_a_fit_time_column_is_missing():
    engineer = FeatureEngineer()
    fit_frame = _frame(["a", "b", "c"])
    engineer.scale_features(fit_frame, fit=True)

    assert engineer.scale_features(fit_frame[["a", "b"]], fit=False) is None
    assert engineer.scale_features(fit_frame[["a", "b"]], fit=False) is None


def test_transform_skips_when_an_unexpected_column_appears():
    engineer = FeatureEngineer()
    fit_frame = _frame(["a", "b"])
    engineer.scale_features(fit_frame, fit=True)

    extended = fit_frame.copy()
    extended["d"] = 1.0

    assert engineer.scale_features(extended, fit=False) is None
