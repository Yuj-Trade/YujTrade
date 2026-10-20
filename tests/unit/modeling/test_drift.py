"""Feature-drift detection contract.

The detector answers one question: did the live feature distribution move
away from the reference window the current model was trained on?

Three properties are load-bearing and therefore asserted here:

- the two-sample KS statistic is the real statistic (not an approximation),
- the p-value is calibrated (a stationary window is not flagged),
- an insufficient window is reported, never silently treated as "no drift".
"""

import numpy as np
import pandas as pd
import pytest

from modeling.drift import (
    CORRECTION_BONFERRONI,
    DEFAULT_DRIFT_FEATURES,
    STATUS_DRIFT,
    STATUS_INSUFFICIENT,
    STATUS_STABLE,
    build_drift_features,
    corrected_threshold,
    detect_feature_drift,
    drift_summary,
    kolmogorov_survival,
    ks_p_value,
    ks_statistic,
    split_windows,
)

FIXTURES = "tests/fixtures"


def _fixture(name: str) -> pd.DataFrame:
    return pd.read_csv(f"{FIXTURES}/{name}", index_col=0, parse_dates=True)


def _stationary_frame(rows: int = 600, seed: int = 99) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2025-01-01", periods=rows, freq="1h", tz="UTC")
    price = 30000.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.003, rows)))
    opens = price * (1 + rng.uniform(-0.002, 0.002, rows))
    highs = price * (1 + rng.uniform(0, 0.005, rows))
    lows = price * (1 - rng.uniform(0, 0.005, rows))
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": price,
            "volume": rng.uniform(100, 10000, rows),
        },
        index=index,
    )
    frame["high"] = frame[["open", "high", "close"]].max(axis=1)
    frame["low"] = frame[["open", "low", "close"]].min(axis=1)
    return frame


class TestKolmogorovSmirnovStatistic:
    def test_identical_samples_have_zero_statistic(self):
        values = [1.0, 2.0, 3.0, 4.0]
        assert ks_statistic(values, values) == pytest.approx(0.0)

    def test_completely_separated_samples_have_statistic_one(self):
        assert ks_statistic([1.0, 2.0], [10.0, 20.0]) == pytest.approx(1.0)

    def test_statistic_matches_the_reference_definition(self):
        first = [1.0, 3.0, 5.0, 7.0]
        second = [2.0, 4.0, 6.0, 8.0]
        expected = max(
            abs(
                sum(1 for value in first if value <= point) / len(first)
                - sum(1 for value in second if value <= point) / len(second)
            )
            for point in sorted(first + second)
        )
        assert ks_statistic(first, second) == pytest.approx(expected)

    def test_empty_sample_returns_zero(self):
        assert ks_statistic([], [1.0]) == 0.0


class TestKolmogorovPValue:
    @pytest.mark.parametrize(
        "lam,expected",
        [(0.0, 1.0), (0.5, 0.9639), (1.0, 0.2700), (1.36, 0.0495), (2.0, 0.000671)],
    )
    def test_survival_function_matches_published_kolmogorov_values(self, lam, expected):
        assert kolmogorov_survival(lam) == pytest.approx(expected, abs=5e-4)

    def test_p_value_uses_the_finite_sample_corrected_argument(self):
        n = m = 500
        effective = (n * m / (n + m)) ** 0.5
        lam = (effective + 0.12 + 0.11 / effective) * 0.5
        assert ks_p_value(0.5, n, m) == pytest.approx(kolmogorov_survival(lam), abs=1e-12)

    def test_small_statistic_is_not_reported_as_mid_probability(self):
        assert ks_p_value(0.03, 300, 300) > 0.95

    def test_large_statistic_is_almost_certain(self):
        assert ks_p_value(0.9, 300, 300) < 1e-3

    def test_p_value_is_monotonic_in_the_statistic(self):
        values = [ks_p_value(step / 10.0, 400, 400) for step in range(1, 20)]
        assert values == sorted(values, reverse=True)

    def test_empty_sample_has_no_evidence(self):
        assert ks_p_value(0.5, 0, 10) == 1.0


class TestDriftFeatures:
    def test_features_are_derived_from_the_price_frame(self):
        frame = _stationary_frame(rows=300)
        features = build_drift_features(frame)
        assert set(DEFAULT_DRIFT_FEATURES) <= set(features.columns)
        assert len(features) > 250
        assert not features.isna().any().any()

    def test_empty_frame_yields_empty_features(self):
        assert build_drift_features(pd.DataFrame()).empty


class TestDriftDetection:
    def test_shifted_distribution_is_flagged(self):
        frame = _fixture("drift_shifted_1h.csv")
        reference, live = split_windows(frame, 600)
        reports = detect_feature_drift(build_drift_features(reference), build_drift_features(live))
        summary = drift_summary(reports, 0.05, 100)
        assert summary["drifted"] is True
        assert "close_return_1" in summary["drifted_features"]

    def test_stationary_distribution_is_not_flagged(self):
        frame = _fixture("drift_stable_1h.csv")
        reference, live = split_windows(frame, 600)
        reports = detect_feature_drift(build_drift_features(reference), build_drift_features(live))
        summary = drift_summary(reports, 0.05, 100)
        assert summary["drifted"] is False
        assert summary["drifted_features"] == []

    def test_short_window_is_reported_as_insufficient_not_as_drift(self):
        frame = _stationary_frame(rows=120)
        reference, live = split_windows(frame, 60)
        reports = detect_feature_drift(build_drift_features(reference), build_drift_features(live))
        assert all(report.status == STATUS_INSUFFICIENT for report in reports)
        assert all(report.p_value is None for report in reports)
        assert all(report.drifted is False for report in reports)

    def test_multiple_testing_correction_is_applied(self):
        frame = _stationary_frame(rows=600)
        reference, live = split_windows(frame, 300)
        reports = detect_feature_drift(build_drift_features(reference), build_drift_features(live))
        summary = drift_summary(reports, 0.05, 100)
        assert summary["correction"] == CORRECTION_BONFERRONI
        assert summary["adjusted_alpha"] == pytest.approx(0.05 / len(DEFAULT_DRIFT_FEATURES))
        assert summary["alpha"] == pytest.approx(0.05)
        for report in reports:
            assert report.threshold == pytest.approx(summary["adjusted_alpha"])

    def test_correction_threshold_scales_with_feature_count(self):
        assert corrected_threshold(0.05, 4) == pytest.approx(0.0125)
        assert corrected_threshold(0.05, 1) == pytest.approx(0.05)

    def test_report_statuses_are_consistent(self):
        frame = _fixture("drift_shifted_1h.csv")
        reference, live = split_windows(frame, 600)
        reports = detect_feature_drift(build_drift_features(reference), build_drift_features(live))
        for report in reports:
            if report.drifted:
                assert report.status == STATUS_DRIFT
            elif report.p_value is not None:
                assert report.status == STATUS_STABLE

    def test_summary_is_json_serializable_and_versioned(self):
        frame = _fixture("drift_stable_1h.csv")
        reference, live = split_windows(frame, 600)
        reports = detect_feature_drift(build_drift_features(reference), build_drift_features(live))
        summary = drift_summary(reports, 0.05, 100)
        assert summary["schema_version"] == 1
        assert isinstance(summary["reports"], list)
        assert summary["reports"]
        for report in summary["reports"]:
            assert {"feature", "ks_statistic", "p_value", "drifted", "status"} <= set(report)


class TestWindowSplit:
    def test_split_keeps_rows_and_order(self):
        frame = _stationary_frame(rows=100)
        reference, live = split_windows(frame, 30)
        assert len(reference) == 70
        assert len(live) == 30
        assert reference.index[-1] < live.index[0]

    def test_window_larger_than_frame_returns_empty_live_window(self):
        frame = _stationary_frame(rows=50)
        reference, live = split_windows(frame, 100)
        assert len(reference) == 50
        assert live.empty
