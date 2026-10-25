import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data.data_validator import DataQualityChecker

_PRISTINE: type | None = None


def _pristine_checker():
    """A checker whose freshness hook is not monkeypatched by the golden recorder."""
    global _PRISTINE
    if _PRISTINE is None:
        path = Path(__file__).resolve().parents[3] / "data" / "data_validator.py"
        spec = importlib.util.spec_from_file_location("data_validator_pristine", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PRISTINE = module.DataQualityChecker
    return _PRISTINE()


@pytest.fixture
def checker():
    return DataQualityChecker()


def _frame(rows=600, freq="1h", end=None, price=50000.0):
    end = end or datetime.now(UTC)
    index = pd.date_range(end=end, periods=rows, freq=freq, tz="UTC")
    close = pd.Series(np.full(rows, price), index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": pd.Series(np.full(rows, 1000.0), index=index),
        },
        index=index,
    )


def _holed_frame(rows=100, gap_hours=12):
    now = datetime.now(UTC)
    second = pd.date_range(end=now, periods=rows, freq="h", tz="UTC")
    first_end = second[0] - pd.Timedelta(hours=gap_hours)
    first = pd.date_range(end=first_end, periods=rows, freq="h", tz="UTC")
    index = first.append(second)
    close = pd.Series(np.full(len(index), 50000.0), index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": pd.Series(np.full(len(index), 1000.0), index=index),
        },
        index=index,
    )


class TestValidateDataQuality:
    def test_valid_frame_passes(self, checker, valid_1h_ohlcv):
        is_valid, message = checker.validate_data_quality(valid_1h_ohlcv, "1h")

        assert is_valid is True
        assert message == "Data quality OK"

    def test_none_frame_fails(self, checker):
        is_valid, message = checker.validate_data_quality(None, "1h")

        assert is_valid is False
        assert "None or empty" in message

    def test_empty_frame_fails(self, checker):
        is_valid, message = checker.validate_data_quality(pd.DataFrame(), "1h")

        assert is_valid is False
        assert "None or empty" in message

    def test_insufficient_rows_fail(self, checker, insufficient_ohlcv):
        is_valid, message = checker.validate_data_quality(insufficient_ohlcv, "1h")

        assert is_valid is False
        assert "Insufficient data" in message

    def test_missing_columns_fail(self, checker):
        frame = _frame().drop(columns=["close", "volume"])
        is_valid, message = checker.validate_data_quality(frame, "1h")

        assert is_valid is False
        assert "Missing required columns" in message

    def test_high_below_low_fails(self, checker):
        frame = _frame()
        frame["high"] = frame["low"] - 1.0
        is_valid, message = checker.validate_data_quality(frame, "1h")

        assert is_valid is False
        assert "high is less than low" in message

    def test_zero_or_negative_prices_fail(self, checker):
        frame = _frame()
        frame.loc[frame.index[10], "close"] = 0.0
        is_valid, message = checker.validate_data_quality(frame, "1h")

        assert is_valid is False
        assert "zero or negative prices" in message

    def test_stale_frame_fails(self):
        checker = _pristine_checker()
        frame = _frame(end=datetime.now(UTC) - timedelta(days=10))
        is_valid, message = checker.validate_data_quality(frame, "1h")

        assert is_valid is False
        assert "stale" in message

    def test_heavy_nulls_fail(self, checker):
        frame = _frame()
        frame.loc[frame.index[:400], "close"] = np.nan

        is_valid, message = checker.validate_data_quality(frame, "1h")

        assert is_valid is False
        assert "Too many null values" in message

    def test_few_nulls_are_tolerated(self, checker):
        frame = _frame()
        frame.loc[frame.index[0], "close"] = np.nan

        is_valid, _ = checker.validate_data_quality(frame, "1h")

        assert is_valid is True

    def test_extreme_move_only_warns(self, checker):
        frame = _frame(price=50000.0)
        frame.loc[frame.index[300], "close"] = 1000.0

        is_valid, _ = checker.validate_data_quality(frame, "1h")

        assert is_valid is True

    def test_low_volume_only_warns(self, checker):
        frame = _frame()
        frame["volume"] = 0.1

        is_valid, _ = checker.validate_data_quality(frame, "1h")

        assert is_valid is True

    def test_duplicate_timestamps_only_warn(self, checker):
        frame = _frame(rows=600)
        frame = pd.concat([frame, frame.tail(1)])
        is_valid, _ = checker.validate_data_quality(frame, "1h")

        assert is_valid is True

    def test_unknown_timeframe_uses_the_default_minimum(self, checker):
        frame = _frame(rows=250)

        is_valid, _ = checker.validate_data_quality(frame, "3m")

        assert is_valid is True


class TestRepairOhlcv:
    def test_none_frame_is_returned_unchanged(self, checker):
        assert checker.repair_ohlcv(None, "1h") is None

    def test_non_datetime_index_is_returned_unchanged(self, checker):
        frame = pd.DataFrame({"close": [1.0, 2.0]})

        assert checker.repair_ohlcv(frame, "1h") is frame

    def test_unsorted_frame_is_sorted(self, checker):
        frame = _frame(rows=10).sort_index(ascending=False)

        repaired = checker.repair_ohlcv(frame, "1h")

        assert repaired.index.is_monotonic_increasing

    def test_unknown_timeframe_skips_the_gap_check(self, checker):
        frame = _frame(rows=10)

        repaired = checker.repair_ohlcv(frame, "3m")

        assert repaired.index.equals(frame.index)

    def test_single_row_is_returned_sorted(self, checker):
        frame = _frame(rows=1)

        repaired = checker.repair_ohlcv(frame, "1h")

        assert len(repaired) == 1

    def test_small_gap_is_interpolated(self, checker, small_gap_ohlcv):
        repaired = checker.repair_ohlcv(small_gap_ohlcv, "1h")

        assert len(repaired) == len(small_gap_ohlcv) + 1
        assert not repaired["close"].isna().any()
        assert not repaired["volume"].isna().any()
        assert (repaired["high"] >= repaired[["open", "close"]].max(axis=1)).all()
        assert (repaired["low"] <= repaired[["open", "close"]].min(axis=1)).all()

    def test_gap_beyond_tolerance_raises(self, checker):
        frame = _frame(rows=100)
        frame = frame.drop(frame.index[50:90])

        with pytest.raises(ValueError, match="gap exceeds repair tolerance"):
            checker.repair_ohlcv(frame, "1h")

    def test_complete_series_is_returned_without_reindexing(self, checker):
        frame = _frame(rows=50)

        repaired = checker.repair_ohlcv(frame, "1h")

        assert repaired.index.equals(frame.index)


class TestFreshnessAndDuplicates:
    @pytest.mark.parametrize("timeframe", ["1h", "4h", "1d", "1w", "1M"])
    def test_recent_data_is_fresh(self, timeframe):
        checker = _pristine_checker()
        frame = _frame(
            rows=5,
            freq={"1h": "1h", "4h": "4h", "1d": "1D", "1w": "1W", "1M": "30D"}[timeframe],
        )

        assert bool(checker._check_data_freshness(frame, timeframe)) is True

    def test_old_data_is_not_fresh(self):
        checker = _pristine_checker()
        frame = _frame(rows=5, end=datetime.now(UTC) - timedelta(days=30))

        assert bool(checker._check_data_freshness(frame, "1h")) is False

    def test_empty_frame_is_not_fresh(self):
        checker = _pristine_checker()

        assert bool(checker._check_data_freshness(pd.DataFrame(), "1h")) is False

    def test_duplicate_index_is_detected(self, checker, duplicate_timestamps_ohlcv):
        assert bool(checker._detect_duplicate_timestamps(duplicate_timestamps_ohlcv)) is True

    def test_unique_index_is_not_duplicated(self, checker, valid_1h_ohlcv):
        assert bool(checker._detect_duplicate_timestamps(valid_1h_ohlcv)) is False

    def test_non_datetime_index_has_no_duplicates(self, checker):
        assert bool(checker._detect_duplicate_timestamps(pd.DataFrame({"close": [1.0]}))) is False


class TestQualityScore:
    def test_perfect_data_scores_high(self, checker, valid_1h_ohlcv):
        score = checker.calculate_overall_quality_score(valid_1h_ohlcv, "1h")

        assert 0.5 <= score <= 1.0

    def test_score_is_bounded(self, checker, valid_1h_ohlcv):
        score = checker.calculate_overall_quality_score(valid_1h_ohlcv, "1h")

        assert 0.0 <= score <= 1.0

    def test_invalid_data_scores_lower_than_valid_data(self, checker, valid_1h_ohlcv):
        broken = valid_1h_ohlcv.copy()
        broken["close"] = 0.0

        assert checker.calculate_overall_quality_score(
            broken, "1h"
        ) < checker.calculate_overall_quality_score(valid_1h_ohlcv, "1h")

    def test_large_gap_is_penalised_not_raised(self, checker):
        score = checker.calculate_overall_quality_score(_holed_frame(rows=100, gap_hours=12), "1h")

        assert 0.0 <= score < 1.0

    def test_weighted_null_ratio_of_empty_frame_is_one(self, checker):
        assert checker._calculate_weighted_null_ratio(pd.DataFrame()) == 1.0

    def test_weighted_null_ratio_of_complete_frame_is_zero(self, checker, valid_1h_ohlcv):
        assert checker._calculate_weighted_null_ratio(valid_1h_ohlcv) == pytest.approx(0.0)

    def test_price_columns_weigh_more_than_volume(self, checker):
        frame = _frame(rows=100)
        frame.loc[frame.index[0], "close"] = np.nan
        price_null = checker._calculate_weighted_null_ratio(frame)

        frame = _frame(rows=100)
        frame.loc[frame.index[0], "volume"] = np.nan
        volume_null = checker._calculate_weighted_null_ratio(frame)

        assert price_null > volume_null


class TestTrendPersistence:
    def test_short_frame_is_not_persistent(self, checker):
        persistent, penalty = checker.check_trend_persistence(_frame(rows=10))

        assert bool(persistent) is False
        assert penalty == pytest.approx(0.3)

    def test_steady_trend_is_persistent(self, checker):
        frame = _frame(rows=100)
        frame["close"] = np.linspace(100, 200, 100)

        persistent, penalty = checker.check_trend_persistence(frame)

        assert bool(persistent) is True
        assert penalty == pytest.approx(0.0)

    def test_choppy_series_is_not_persistent(self, checker):
        frame = _frame(rows=100)
        frame["close"] = 100 + 10 * np.sin(np.arange(100) * 1.5)

        persistent, penalty = checker.check_trend_persistence(frame)

        assert bool(persistent) is False
        assert 0.0 < penalty <= 0.3

    @pytest.mark.parametrize(("volatility", "divisor"), [(0.01, 9), (0.04, 7), (0.10, 5)])
    def test_volatility_adjusts_the_allowed_changes(self, checker, volatility, divisor):
        assert checker._get_volatility_adjusted_max_changes(48, volatility) == 48 // divisor

    def test_allowed_changes_has_a_floor(self, checker):
        assert checker._get_volatility_adjusted_max_changes(10, 0.10) == 4


class TestVolumeSufficiency:
    def test_missing_volume_column_is_sufficient(self, checker):
        frame = _frame(rows=100).drop(columns=["volume"])

        assert bool(checker.check_sufficient_volume(frame)) is True

    def test_short_frame_is_sufficient(self, checker):
        assert bool(checker.check_sufficient_volume(_frame(rows=10))) is True

    def test_volume_collapse_is_insufficient(self, checker):
        frame = _frame(rows=100)
        frame.loc[frame.index[-20:], "volume"] = 1.0

        assert bool(checker.check_sufficient_volume(frame)) is False

    def test_stable_volume_is_sufficient(self, checker):
        assert bool(checker.check_sufficient_volume(_frame(rows=100))) is True

    def test_zero_historical_volume_requires_recent_volume(self, checker):
        frame = _frame(rows=100)
        frame["volume"] = 0.0
        frame.loc[frame.index[-20:], "volume"] = 5.0

        assert bool(checker.check_sufficient_volume(frame)) is True


class TestDataGaps:
    def test_non_datetime_index_has_no_gaps(self, checker):
        assert checker.detect_data_gaps(pd.DataFrame({"close": [1.0, 2.0]})) == (False, 0.0)

    def test_single_row_has_no_gaps(self, checker):
        assert checker.detect_data_gaps(_frame(rows=1)) == (False, 0.0)

    def test_regular_series_has_no_gaps(self, checker):
        assert checker.detect_data_gaps(_frame(rows=50)) == (False, 0.0)

    def test_small_gap_returns_a_penalty(self, checker):
        has_gaps, penalty = checker.detect_data_gaps(_holed_frame(rows=100, gap_hours=12))

        assert bool(has_gaps) is True
        assert 0.0 < penalty <= 0.5

    def test_large_gap_raises(self, checker):
        with pytest.raises(ValueError, match="Data gap too large"):
            checker.detect_data_gaps(_holed_frame(rows=100, gap_hours=200))

    @pytest.mark.parametrize(
        ("freq", "expected"),
        [("1W", "1W"), ("1M", "1M"), ("1D", "1D"), ("h", "h"), (None, None)],
    )
    def test_frequency_mapping(self, checker, freq, expected):
        assert checker._map_freq_str(freq) == expected
