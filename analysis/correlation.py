from typing import Any

import pandas as pd

from config.logger import logger


class IndicatorCorrelationManager:
    def __init__(self, correlation_threshold: float = 0.7):
        self.correlation_matrix: pd.DataFrame | None = None
        self.correlation_threshold = correlation_threshold

    def compute_correlations(
        self,
        processed_results: dict[str, Any],
        history: dict[str, pd.Series] | None = None,
    ):
        self.correlation_matrix = None

        if not history:
            logger.warning(
                "decorrelation_disabled: historical indicator series unavailable; "
                "neutral weights applied."
            )
            return

        aligned = {}
        for name in processed_results.keys():
            series = history.get(name)
            if series is None:
                continue
            try:
                s = pd.Series(series).dropna()
                if len(s) >= 10:
                    aligned[name] = s
            except (TypeError, ValueError):
                continue

        if len(aligned) < 2:
            return

        df = pd.DataFrame(aligned).dropna()
        if df.empty or len(df) < 10 or len(df.columns) < 2:
            return

        self.correlation_matrix = df.corr()

    def get_decorrelation_weights(self, processed_results: dict[str, Any]) -> dict[str, float]:
        if self.correlation_matrix is None or self.correlation_matrix.empty:
            return {name: 1.0 for name in processed_results.keys()}

        weights = {}
        correlated_groups = []
        indicators = list(self.correlation_matrix.columns)

        for i, indicator1 in enumerate(indicators):
            is_grouped = any(indicator1 in group for group in correlated_groups)
            if is_grouped:
                continue

            new_group = {indicator1}
            for j in range(i + 1, len(indicators)):
                indicator2 = indicators[j]
                if self.correlation_matrix.loc[indicator1, indicator2] > self.correlation_threshold:
                    new_group.add(indicator2)

            if len(new_group) > 1:
                correlated_groups.append(new_group)

        for group in correlated_groups:
            group_size = len(group)
            for indicator in group:
                weights[indicator] = 1.0 / group_size

        for indicator in processed_results.keys():
            if indicator not in weights:
                weights[indicator] = 1.0

        return weights
