import math
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

DRIFT_SCHEMA_VERSION = 1
STATUS_DRIFT = "drift"
STATUS_STABLE = "stable"
STATUS_INSUFFICIENT = "insufficient_data"
CORRECTION_BONFERRONI = "bonferroni"
DEFAULT_DRIFT_FEATURES = (
    "close_return_1",
    "close_return_5",
    "volume_return_1",
    "intrabar_range",
)
FEATURE_STRIDES = {
    "close_return_1": 1,
    "close_return_5": 5,
    "volume_return_1": 1,
    "intrabar_range": 1,
}
VOLUME_RATIO_WINDOW = 20
VOLUME_RATIO_MIN_PERIODS = 5


@dataclass(frozen=True)
class DriftReport:
    feature: str
    ks_statistic: float
    p_value: float | None
    drifted: bool
    reference_samples: int
    live_samples: int
    status: str
    threshold: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ks_statistic(reference: Any, live: Any) -> float:
    first = sorted(float(value) for value in reference)
    second = sorted(float(value) for value in live)
    if not first or not second:
        return 0.0
    n = len(first)
    m = len(second)
    index_first = 0
    index_second = 0
    largest = 0.0
    while index_first < n and index_second < m:
        boundary = min(first[index_first], second[index_second])
        while index_first < n and first[index_first] <= boundary:
            index_first += 1
        while index_second < m and second[index_second] <= boundary:
            index_second += 1
        gap = abs(index_first / n - index_second / m)
        if gap > largest:
            largest = gap
    return largest


def kolmogorov_survival(lam: float) -> float:
    if lam <= 0.0:
        return 1.0
    if lam < 1.18:
        total = 0.0
        for index in range(1, 101):
            odd = 2 * index - 1
            exponent = -(odd * odd * math.pi * math.pi) / (8.0 * lam * lam)
            term = math.exp(exponent)
            total += term
            if term < 1e-16 * total:
                break
        cdf = math.sqrt(2.0 * math.pi) / lam * total
        return min(max(1.0 - cdf, 0.0), 1.0)
    total = 0.0
    sign = 1.0
    for index in range(1, 101):
        term = sign * math.exp(-2.0 * lam * lam * index * index)
        total += term
        if abs(term) < 1e-14 * abs(total):
            break
        sign = -sign
    return min(max(2.0 * total, 0.0), 1.0)


def ks_p_value(statistic: float, n: int, m: int) -> float:
    if n < 1 or m < 1 or statistic <= 0.0:
        return 1.0
    effective = math.sqrt(n * m / (n + m))
    lam = (effective + 0.12 + 0.11 / effective) * statistic
    return kolmogorov_survival(lam)


def build_drift_features(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    safe_close = close.replace(0.0, float("nan"))
    features = pd.DataFrame(index=frame.index)
    features["close_return_1"] = close.pct_change()
    features["close_return_5"] = close.pct_change(5)
    features["volume_return_1"] = volume.pct_change()
    features["intrabar_range"] = (high - low) / safe_close
    return features.replace([float("inf"), float("-inf")], float("nan")).dropna(how="any")


def split_windows(frame: pd.DataFrame, live_window: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame is None or len(frame) == 0:
        return pd.DataFrame(), pd.DataFrame()
    if live_window < 1:
        return frame, pd.DataFrame()
    if len(frame) <= live_window:
        return frame, frame.iloc[0:0]
    return frame.iloc[:-live_window], frame.iloc[-live_window:]


def _column_values(source: Any, feature: str) -> list[float]:
    if source is None:
        return []
    if isinstance(source, pd.DataFrame):
        if feature not in source.columns:
            return []
        series = source[feature]
    elif isinstance(source, dict):
        if feature not in source:
            return []
        series = pd.Series(source[feature])
    else:
        return []
    values = pd.to_numeric(series, errors="coerce").dropna()
    stride = FEATURE_STRIDES.get(feature, 1)
    if stride > 1:
        values = values.iloc[::stride]
    return [float(value) for value in values]


def corrected_threshold(alpha: float, feature_count: int) -> float:
    if feature_count < 1:
        return float(alpha)
    return float(alpha) / float(feature_count)


def detect_feature_drift(
    reference: Any,
    live: Any,
    features: Any = None,
    alpha: float = 0.05,
    min_window: int = 100,
) -> list[DriftReport]:
    names = list(features) if features else list(DEFAULT_DRIFT_FEATURES)
    threshold = corrected_threshold(alpha, len(names))
    reports: list[DriftReport] = []
    for name in names:
        reference_values = _column_values(reference, name)
        live_values = _column_values(live, name)
        if len(reference_values) < min_window or len(live_values) < min_window:
            reports.append(
                DriftReport(
                    feature=name,
                    ks_statistic=0.0,
                    p_value=None,
                    drifted=False,
                    reference_samples=len(reference_values),
                    live_samples=len(live_values),
                    status=STATUS_INSUFFICIENT,
                    threshold=threshold,
                )
            )
            continue
        statistic = ks_statistic(reference_values, live_values)
        p_value = ks_p_value(statistic, len(reference_values), len(live_values))
        drifted = p_value < threshold
        reports.append(
            DriftReport(
                feature=name,
                ks_statistic=statistic,
                p_value=p_value,
                drifted=drifted,
                reference_samples=len(reference_values),
                live_samples=len(live_values),
                status=STATUS_DRIFT if drifted else STATUS_STABLE,
                threshold=threshold,
            )
        )
    return reports


def drift_summary(reports: list[DriftReport], alpha: float, min_window: int) -> dict[str, Any]:
    drifted = [report.feature for report in reports if report.drifted]
    insufficient = [report.feature for report in reports if report.status == STATUS_INSUFFICIENT]
    threshold = reports[0].threshold if reports else corrected_threshold(alpha, 0)
    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "alpha": float(alpha),
        "adjusted_alpha": float(threshold),
        "correction": CORRECTION_BONFERRONI,
        "min_window": int(min_window),
        "drifted": bool(drifted),
        "drifted_features": drifted,
        "insufficient_features": insufficient,
        "reports": [report.to_dict() for report in reports],
    }
