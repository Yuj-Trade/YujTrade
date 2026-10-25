from abc import ABC, abstractmethod
from typing import Any, Protocol

import numpy as np
import pandas as pd

from common.core import IndicatorResult


class IndicatorInterface(Protocol):
    def calculate(self, data: pd.DataFrame) -> IndicatorResult: ...


def last_finite_value(result: Any) -> float | None:
    if result is None:
        return None

    if isinstance(result, pd.DataFrame):
        if result.empty:
            return None
        row = result.iloc[-1].dropna()
        if row.empty:
            return None
        return float(row.iloc[0])

    if isinstance(result, pd.Series):
        series = result.dropna()
        if series.empty:
            return None
        return float(series.iloc[-1])

    if isinstance(result, np.ndarray):
        flat = np.asarray(result, dtype=np.float64).ravel()
        finite = flat[~np.isnan(flat)]
        if finite.size == 0:
            return None
        return float(finite[-1])

    if isinstance(result, (int, float, np.number)):
        value = float(result)
        return None if np.isnan(value) else value

    return None


def finite_column(result: Any, column: int) -> float | None:
    if result is None or not hasattr(result, "iloc") or result.empty:
        return None
    row = result.iloc[-1]
    if isinstance(row, pd.Series):
        if column >= len(row):
            return None
        value = row.iloc[column]
    else:
        value = row
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(numeric) else numeric


class TechnicalIndicator(ABC):
    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> IndicatorResult:
        pass
