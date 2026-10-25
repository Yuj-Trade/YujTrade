"""Unit tests for common/utils.py helpers.

RateLimiter lives in test_rate_limiter.py; the retry decorator is covered here
together with the indicator normaliser and the price-level helpers.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from common.core import (
    IndicatorResult,
    MarketAnalysis,
    MarketCondition,
    SignalType,
    TrendDirection,
    TrendStrength,
)
from common.utils import (
    IndicatorNormalizer,
    async_retry,
    calculate_correlation_matrix,
    calculate_dynamic_levels,
    calculate_fibonacci_levels,
    calculate_pivot_points,
    calculate_risk_reward_ratio,
    detect_market_regime,
    format_number,
    get_support_resistance_strength,
    validate_signal_timing,
)


def _series(values, freq="h"):
    index = pd.date_range("2024-01-01", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=index, dtype=float)


def _ohlcv(closes, spread=1.0):
    index = pd.date_range("2024-01-01", periods=len(closes), freq="h", tz="UTC")
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close.shift(1).bfill(),
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": pd.Series(1000.0, index=index),
        },
        index=index,
    )


class TestIndicatorNormalizer:
    def setup_method(self):
        self.normalizer = IndicatorNormalizer()

    def test_bounded_indicator_is_scaled_to_minus_one_to_one(self):
        result = self.normalizer.normalize_indicator(
            IndicatorResult("RSI", 50.0, 50.0, "neutral"), "rsi"
        )

        assert result.value == pytest.approx(0.0)

    def test_lower_bound_maps_to_minus_one(self):
        result = self.normalizer.normalize_indicator(
            IndicatorResult("RSI", 0.0, 10.0, "oversold"), "rsi"
        )

        assert result.value == pytest.approx(-1.0)

    def test_upper_bound_maps_to_one(self):
        result = self.normalizer.normalize_indicator(
            IndicatorResult("RSI", 100.0, 10.0, "overbought"), "rsi"
        )

        assert result.value == pytest.approx(1.0)

    def test_unbounded_both_sides_is_returned_unchanged(self):
        original = IndicatorResult("OBV", 1234.5, 10.0, "up")
        assert self.normalizer.normalize_indicator(original, "obv") is original

    def test_positive_only_range_clips_at_one(self):
        result = self.normalizer.normalize_indicator(
            IndicatorResult("Volume", 500.0, 10.0, "high"), "volume"
        )

        assert result.value == pytest.approx(1.0)

    def test_unknown_indicator_uses_the_default_range(self):
        result = self.normalizer.normalize_indicator(
            IndicatorResult("Mystery", 0.0, 10.0, "neutral"), "mystery"
        )

        assert result.value == pytest.approx(0.0)

    def test_nan_value_is_returned_unchanged(self):
        original = IndicatorResult("RSI", float("nan"), 0.0, "neutral")
        assert self.normalizer.normalize_indicator(original, "rsi") is original

    def test_none_value_is_returned_unchanged(self):
        original = IndicatorResult("RSI", None, 0.0, "neutral")
        assert self.normalizer.normalize_indicator(original, "rsi") is original

    def test_object_without_value_attribute_is_returned_unchanged(self):
        class Bare:
            pass

        bare = Bare()
        assert self.normalizer.normalize_indicator(bare, "rsi") is bare

    def test_degenerate_range_returns_zero(self):
        normalizer = IndicatorNormalizer()
        normalizer.expected_ranges["flat"] = (5.0, 5.0)

        result = normalizer.normalize_indicator(
            IndicatorResult("Flat", 5.0, 10.0, "neutral"), "flat"
        )

        assert result.value == 0.0

    def test_negative_only_range_is_scaled(self):
        normalizer = IndicatorNormalizer()
        normalizer.expected_ranges["neg"] = (-float("inf"), 0.0)

        result = normalizer.normalize_indicator(IndicatorResult("Neg", -100.0, 10.0, "low"), "neg")

        assert -1.0 <= result.value <= 1.0


class TestAsyncRetry:
    async def test_returns_on_first_success(self):
        calls = 0

        @async_retry(attempts=3, delay=0.01)
        async def work():
            nonlocal calls
            calls += 1
            return "ok"

        assert await work() == "ok"
        assert calls == 1

    async def test_retries_then_succeeds(self):
        calls = 0

        @async_retry(attempts=3, delay=0.01)
        async def work():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ValueError("transient")
            return "ok"

        assert await work() == "ok"
        assert calls == 3

    async def test_exhausts_attempts_and_reraises(self):
        calls = 0

        @async_retry(attempts=2, delay=0.01)
        async def work():
            nonlocal calls
            calls += 1
            raise ValueError("always")

        with pytest.raises(ValueError, match="always"):
            await work()
        assert calls == 2

    async def test_ignored_exception_is_not_retried(self):
        calls = 0

        @async_retry(attempts=3, delay=0.01, ignore_exceptions=(KeyError,))
        async def work():
            nonlocal calls
            calls += 1
            raise KeyError("fatal")

        with pytest.raises(KeyError):
            await work()
        assert calls == 1

    async def test_unlisted_exception_propagates_immediately(self):
        calls = 0

        @async_retry(attempts=3, delay=0.01, exceptions=(ValueError,))
        async def work():
            nonlocal calls
            calls += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError):
            await work()
        assert calls == 1

    async def test_metadata_is_preserved(self):
        @async_retry(attempts=2, delay=0.01)
        async def documented():
            return 1

        assert documented.__name__ == "documented"


class TestSupportResistance:
    def test_empty_frame_returns_zero(self):
        assert get_support_resistance_strength(pd.DataFrame(), 100.0) == 0.0

    def test_none_level_returns_zero(self):
        assert get_support_resistance_strength(_ohlcv([100, 101, 102]), None) == 0.0

    def test_flat_market_returns_one(self):
        frame = _ohlcv([100, 100, 100], spread=0.0)
        assert get_support_resistance_strength(frame, 100.0) == 1.0

    def test_level_never_touched_returns_zero(self):
        frame = _ohlcv([100, 101, 102, 103], spread=0.5)
        assert get_support_resistance_strength(frame, 500.0) == 0.0

    def test_touched_level_scores_above_zero(self):
        closes = [100, 105, 100, 105, 100, 105, 100, 105, 100, 105]
        frame = _ohlcv(closes, spread=1.0)

        strength = get_support_resistance_strength(frame, 100.0)

        assert 0.0 < strength <= 10.0

    def test_missing_high_column_returns_zero(self):
        frame = pd.DataFrame({"close": [1.0, 2.0]})
        assert get_support_resistance_strength(frame, 1.5) == 0.0


class TestFibonacciLevels:
    def test_uptrend_levels_are_below_the_high(self):
        frame = _ohlcv(list(range(100, 140)), spread=1.0)

        levels = calculate_fibonacci_levels(frame, lookback=20)

        assert levels["fib_0"] == frame["high"].tail(20).max()
        assert levels["fib_100"] == frame["low"].tail(20).min()
        assert levels["fib_500"] < levels["fib_0"]
        assert levels["fib_1618"] > levels["fib_0"]

    def test_downtrend_levels_are_above_the_low(self):
        frame = _ohlcv(list(range(140, 100, -1)), spread=1.0)

        levels = calculate_fibonacci_levels(frame, lookback=20)

        assert levels["fib_0"] == frame["low"].tail(20).min()
        assert levels["fib_100"] == frame["high"].tail(20).max()
        assert levels["fib_500"] > levels["fib_0"]
        assert levels["fib_1618"] < levels["fib_0"]

    def test_lookback_larger_than_the_frame_is_clamped(self):
        frame = _ohlcv([100, 101, 102], spread=1.0)

        levels = calculate_fibonacci_levels(frame, lookback=500)

        assert set(levels) == {
            "fib_0",
            "fib_236",
            "fib_382",
            "fib_500",
            "fib_618",
            "fib_786",
            "fib_100",
            "fib_1272",
            "fib_1618",
        }


class TestPivotPoints:
    def test_empty_frame_returns_empty_dict(self):
        assert calculate_pivot_points(pd.DataFrame()) == {}

    def test_pivot_is_the_mean_of_high_low_close(self):
        frame = pd.DataFrame(
            {"open": [1.0], "high": [12.0], "low": [6.0], "close": [9.0], "volume": [1.0]}
        )

        levels = calculate_pivot_points(frame)

        assert levels["pivot"] == pytest.approx(9.0)
        assert levels["r1"] == pytest.approx(12.0)
        assert levels["s1"] == pytest.approx(6.0)
        assert levels["r2"] > levels["r1"]
        assert levels["s2"] < levels["s1"]
        assert levels["woody_pivot"] == pytest.approx((12 + 6 + 18) / 4)
        assert levels["cam_r4"] > levels["cam_r1"]
        assert levels["cam_s4"] < levels["cam_s1"]


def _market_analysis(volatility=2.0, adx=30.0, supports=None, resistances=None):
    return MarketAnalysis(
        trend=TrendDirection.BULLISH,
        trend_strength=TrendStrength.STRONG,
        volatility=volatility,
        volume_trend="increasing",
        support_levels=supports if supports is not None else [49000.0],
        resistance_levels=resistances if resistances is not None else [52000.0],
        momentum_score=0.5,
        market_condition=MarketCondition.NEUTRAL,
        trend_acceleration=0.1,
        volume_confirmation=True,
        adx=adx,
    )


class TestDynamicLevels:
    def test_buy_levels_bracket_the_entry(self):
        frame = _ohlcv([50000.0] * 30, spread=100.0)

        levels = calculate_dynamic_levels(frame, SignalType.BUY, _market_analysis())

        assert levels["tight_stop"] < levels["primary_entry"]
        assert levels["primary_exit"] > levels["primary_entry"]
        assert levels["breakeven_point"] > levels["primary_entry"]
        assert levels["trailing_stop"] > 0

    def test_sell_levels_bracket_the_entry(self):
        frame = _ohlcv([50000.0] * 30, spread=100.0)

        levels = calculate_dynamic_levels(frame, SignalType.SELL, _market_analysis())

        assert levels["tight_stop"] > levels["primary_entry"]
        assert levels["primary_exit"] < levels["primary_entry"]
        assert levels["breakeven_point"] < levels["primary_entry"]

    def test_zero_volatility_falls_back_to_return_std(self):
        frame = _ohlcv([50000.0 + i for i in range(30)], spread=100.0)
        analysis = _market_analysis(volatility=0.0)

        levels = calculate_dynamic_levels(frame, SignalType.BUY, analysis)

        assert levels["tight_stop"] < levels["primary_entry"]

    def test_support_and_resistance_are_used_when_close(self):
        frame = _ohlcv([50000.0] * 30, spread=100.0)
        analysis = _market_analysis(supports=[49900.0], resistances=[50400.0])

        levels = calculate_dynamic_levels(frame, SignalType.BUY, analysis)

        assert levels["tight_stop"] == pytest.approx(49900.0)
        assert levels["primary_exit"] == pytest.approx(50400.0)


class TestRiskReward:
    def test_hold_returns_zero(self):
        assert calculate_risk_reward_ratio(100.0, 90.0, 120.0, SignalType.HOLD) == 0.0

    def test_zero_risk_returns_the_sentinel(self):
        assert calculate_risk_reward_ratio(100.0, 100.0, 120.0, SignalType.BUY) == 999.0

    def test_buy_ratio_accounts_for_costs(self):
        ratio = calculate_risk_reward_ratio(100.0, 90.0, 120.0, SignalType.BUY)

        assert 1.5 < ratio < 3.0

    def test_sell_ratio_is_symmetric(self):
        buy = calculate_risk_reward_ratio(100.0, 90.0, 120.0, SignalType.BUY)
        sell = calculate_risk_reward_ratio(100.0, 110.0, 80.0, SignalType.SELL)

        assert sell == pytest.approx(buy)

    def test_negative_effective_risk_is_not_divided(self):
        ratio = calculate_risk_reward_ratio(0.0, 0.0, 0.0, SignalType.BUY)

        assert ratio == 999.0


class TestSignalTiming:
    def test_short_history_is_accepted(self):
        frame = _ohlcv([100, 101, 102], spread=1.0)

        valid, reason = validate_signal_timing(frame, SignalType.BUY)

        assert valid is True
        assert "Not enough data" in reason

    def test_flat_market_returns_invalid_price_range(self):
        frame = _ohlcv([100.0] * 20, spread=0.0)

        valid, reason = validate_signal_timing(frame, SignalType.BUY)

        assert valid is True
        assert "Invalid price range" in reason

    def test_buy_at_the_recent_high_is_rejected(self):
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
        frame = _ohlcv(closes, spread=0.5)

        valid, reason = validate_signal_timing(frame, SignalType.BUY)

        assert valid is False
        assert "recent high" in reason

    def test_sell_at_the_recent_low_is_rejected(self):
        closes = [109, 108, 107, 106, 105, 104, 103, 102, 101, 100]
        frame = _ohlcv(closes, spread=0.5)

        valid, reason = validate_signal_timing(frame, SignalType.SELL)

        assert valid is False
        assert "recent low" in reason

    def test_long_shadow_candle_is_rejected(self):
        frame = _ohlcv([100, 101, 102, 103, 104, 103, 102, 101], spread=1.0)
        frame.iloc[-1, frame.columns.get_loc("open")] = 101.0
        frame.iloc[-1, frame.columns.get_loc("close")] = 101.05
        frame.iloc[-1, frame.columns.get_loc("high")] = 101.6
        frame.iloc[-1, frame.columns.get_loc("low")] = 100.5

        valid, reason = validate_signal_timing(frame, SignalType.BUY)

        assert valid is False
        assert "shadows" in reason


class TestMarketRegime:
    def test_regime_reports_every_field(self):
        rng = np.random.default_rng(3)
        closes = 100 + np.cumsum(rng.standard_normal(200))
        frame = _ohlcv(list(closes), spread=1.0)

        regime = detect_market_regime(frame)

        assert set(regime) == {
            "market_type",
            "adx",
            "volatility",
            "volatility_regime",
            "trend_persistence",
            "hurst_exponent",
            "recommended_strategy",
        }
        assert regime["market_type"] in {"trending", "ranging", "transitional"}
        assert regime["recommended_strategy"] in {
            "trend_following",
            "mean_reversion",
            "breakout",
            "balanced",
        }

    def test_short_frame_is_clamped_to_available_rows(self):
        frame = _ohlcv([100, 101, 102, 103, 104], spread=1.0)

        regime = detect_market_regime(frame, lookback=50)

        assert regime["adx"] >= 0


class TestFormattingAndCorrelation:
    def test_format_number_groups_thousands(self):
        assert format_number(1234567.891) == "1,234,567.89"

    def test_format_number_honours_decimals(self):
        assert format_number(1.5, decimals=0) == "2"

    def test_empty_symbols_return_an_empty_matrix(self):
        assert calculate_correlation_matrix({}).empty

    def test_matrix_is_square_and_diagonal_is_one(self):
        index = pd.date_range("2024-01-01", periods=50, freq="h", tz="UTC")
        rng = np.random.default_rng(11)
        data = {
            "BTC": pd.DataFrame({"close": 100 + np.cumsum(rng.standard_normal(50))}, index=index),
            "ETH": pd.DataFrame({"close": 50 + np.cumsum(rng.standard_normal(50))}, index=index),
        }

        matrix = calculate_correlation_matrix(data)

        assert matrix.shape == (2, 2)
        assert matrix.loc["BTC", "BTC"] == pytest.approx(1.0)
        assert -1.0 <= matrix.loc["BTC", "ETH"] <= 1.0

    async def test_retry_backoff_does_not_block_the_loop(self):
        order = []

        @async_retry(attempts=2, delay=0.01, jitter=0.0)
        async def work():
            order.append("work")
            raise ValueError("again")

        async def ticker():
            order.append("tick")

        with pytest.raises(ValueError):
            await asyncio.gather(work(), ticker())

        assert "tick" in order
