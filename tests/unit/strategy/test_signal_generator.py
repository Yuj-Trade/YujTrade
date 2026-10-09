"""
P1 Tests for SignalGenerator — Phases 11 + 12.

Covers:
- generate_signal error contract (gap 30): invalid data → InsufficientDataError (raise),
  HOLD/between-thresholds/rr<min → None, success → complete TradingSignal.
- include_external=False → all external_data None + no provider calls (spy, gap 14).
- include_ml=False → ml_predictions empty + no model calls (spy, gap 14).
- adjust_weights_by_regime (gap 6): ranging ×1.5 mean-reversion, trending ×1.3 trend,
  others unchanged, input not mutated.
- combined_weights = regime × decorrelation product.
- _hurst_range mappings.
- threshold_regime format f"{vol_regime}|{hurst_range}" contract with
  BacktestingEngine._flush_calibration partition("|").
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from strategy.signal_generator import SignalGenerator
from common.core import TradingSignal, SignalType, MarketAnalysis
from common.exceptions import InsufficientDataError
from common.constants import LONG_TERM_CONFIG, AnalysisComponent
from common.utils import detect_market_regime
from config.settings import ConfigManager


# ─── Fixtures ───

@pytest.fixture
def config_manager(tmp_path):
    """ConfigManager واقعی با فایل‌های tmp — DEFAULT_CONFIG خالص."""
    return ConfigManager(
        config_path=str(tmp_path / "config.json"),
        weights_path=str(tmp_path / "weights.json"),
    )


@pytest.fixture
def mock_data_provider():
    """MarketDataProvider mock با تمام متدهای get_* — AsyncMock return_value=None."""
    dp = MagicMock(name="MarketDataProviderMock")
    for name in [
        "get_derivatives_data", "get_fundamental_data", "get_onchain_data",
        "get_order_book", "get_macro_data", "get_trending_data", "get_all_indices",
    ]:
        setattr(dp, name, AsyncMock(return_value=None))
    dp.get_news_sentiment = AsyncMock(return_value=None)
    return dp


@pytest.fixture
def mock_model_manager():
    """ModelManager mock — predict_with_confidence پیش‌فرض None."""
    mm = MagicMock(name="ModelManagerMock")
    mm.predict_with_confidence = AsyncMock(return_value=None)
    return mm


@pytest.fixture
def generator(config_manager, mock_data_provider, mock_model_manager):
    """SignalGenerator با وابستگی‌های mock شده."""
    return SignalGenerator(mock_data_provider, mock_model_manager, config_manager)


@pytest.fixture
def sideways_analysis(sideways_weak_analysis):
    """MarketAnalysis instance از fixture conftest."""
    return MarketAnalysis(**sideways_weak_analysis)


@pytest.fixture
def rigged_generator(config_manager, mock_data_provider, mock_model_manager, sideways_analysis):
    """SignalGenerator با scorer کنترل‌شده — final_score از بیرون تعیین می‌شود."""
    gen = SignalGenerator(mock_data_provider, mock_model_manager, config_manager)
    gen.market_analyzer.analyze_market_condition = MagicMock(return_value=sideways_analysis)
    gen.scorer.calculate_combined_score = MagicMock(return_value=(75.0, ["rigged reason"]))
    return gen


# ─── Helpers ───

RANGE_DETECT = {
    "market_type": "ranging",
    "volatility_regime": "low",
    "adx": 15.0,
    "volatility": 20.0,
    "trend_persistence": "mean_reverting",
    "hurst_exponent": 0.4,
    "recommended_strategy": "mean_reversion",
}

TREND_DETECT = {
    "market_type": "trending",
    "volatility_regime": "high",
    "adx": 35.0,
    "volatility": 40.0,
    "trend_persistence": "persistent",
    "hurst_exponent": 0.6,
    "recommended_strategy": "trend_following",
}

NORMAL_DETECT = {
    "market_type": "transitional",
    "volatility_regime": "normal",
    "adx": 22.0,
    "volatility": 30.0,
    "trend_persistence": "random_walk",
    "hurst_exponent": 0.5,
    "recommended_strategy": "balanced",
}

# controllable dynamic levels with rr >= 2.8 (BUY)
BUY_LEVELS = {
    "primary_entry": 100.0,
    "secondary_entry": 100.0,
    "primary_exit": 115.0,
    "secondary_exit": 115.0,
    "tight_stop": 95.0,
    "wide_stop": 95.0,
    "breakeven_point": 102.5,
    "trailing_stop": 4.0,
}

# SELL levels with rr >= 2.8
SELL_LEVELS = {
    "primary_entry": 100.0,
    "secondary_entry": 100.0,
    "primary_exit": 85.0,
    "secondary_exit": 85.0,
    "tight_stop": 105.0,
    "wide_stop": 105.0,
    "breakeven_point": 97.5,
    "trailing_stop": 4.0,
}

# BAD levels: rr < 2.8
BAD_RR_LEVELS = {
    "primary_entry": 100.0,
    "secondary_entry": 100.0,
    "primary_exit": 101.0,
    "secondary_exit": 101.0,
    "tight_stop": 99.0,
    "wide_stop": 99.0,
    "breakeven_point": 100.5,
    "trailing_stop": 0.5,
}


# ─── generate_signal Core Tests ───

class TestGenerateSignalErrorContract:
    """قرارداد خطای واحد (قاعده ۳۰):
    - بازگرداندن None = «سیگنالی نیست» (HOLD، رد RR) — تصمیم سالم تحلیل.
    - raise = «تحلیل شکست خورد» (داده بی‌کیفیت) — باید به جمع‌کننده برسد.
    """

    @pytest.mark.asyncio
    async def test_invalid_data_raises_insufficient_data_error(self, generator, insufficient_ohlcv):
        with pytest.raises(InsufficientDataError, match="Data quality check failed"):
            await generator.generate_signal("BTC/USDT", "1h", insufficient_ohlcv)

    @pytest.mark.asyncio
    async def test_missing_columns_raises(self, generator):
        """فقدان ستون‌های الزامی (داده بلند، رد نشده به‌خاطر کمبود ردیف) →
        raise — نه None (قاعده ۳۰)."""
        long_missing = pd.DataFrame(
            {"open": [50000.0] * 600, "high": [50500.0] * 600},
            index=pd.date_range(
                end=pd.Timestamp.now(tz="UTC"), periods=600, freq="1h", tz="UTC"
            ),
        )
        with pytest.raises(InsufficientDataError, match="Missing required columns"):
            await generator.generate_signal("BTC/USDT", "1h", long_missing)

    @pytest.mark.asyncio
    async def test_hold_between_thresholds_returns_none(self, rigged_generator, valid_1h_ohlcv):
        """|final_score| < threshold → HOLD → None (نه Exception)."""
        rigged_generator.scorer.calculate_combined_score.return_value = (10.0, ["hold reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels") as mock_levels:
            result = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        assert result is None
        mock_levels.assert_not_called()  # هولد قبل از محاسبه Levels برگردانده می‌شود

    @pytest.mark.asyncio
    async def test_rr_ratio_below_minimum_returns_none(self, rigged_generator, valid_1h_ohlcv):
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BAD_RR_LEVELS):
            result = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        assert result is None  # rr ~0.74 < 2.8 → None

    @pytest.mark.asyncio
    async def test_sell_path_returns_complete_signal(self, rigged_generator, valid_1h_ohlcv):
        rigged_generator.scorer.calculate_combined_score.return_value = (-75.0, ["sell reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=SELL_LEVELS):
            signal = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        assert isinstance(signal, TradingSignal)
        assert signal.signal_type == SignalType.SELL
        assert signal.entry_price == 100.0
        assert signal.exit_price == 85.0
        assert signal.stop_loss == 105.0
        assert signal.risk_reward_ratio == pytest.approx(2.8835, abs=1e-3)

    @pytest.mark.asyncio
    async def test_buy_path_returns_complete_signal_with_all_fields(self, rigged_generator, valid_1h_ohlcv):
        """موفقیت → TradingSignal کامل با threshold_used/threshold_regime."""
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        assert isinstance(signal, TradingSignal)
        assert signal.symbol == "BTC/USDT"
        assert signal.signal_type == SignalType.BUY
        assert signal.entry_price == 100.0
        assert signal.exit_price == 115.0
        assert signal.stop_loss == 95.0
        assert signal.timeframe == "1h"
        assert signal.confidence_score == 75.0  # abs(final_score)
        assert signal.risk_reward_ratio == pytest.approx(2.8835, abs=1e-3)
        assert signal.reasons == ["buy reason"]
        assert signal.threshold_used == 50.0  # config default signal_threshold
        # threshold_regime = "normal|mid" (vol_regime="normal", hurst=0.5 → "mid")
        assert signal.threshold_regime == "normal|mid"
        assert signal.ml_confidence == 0.0  # include_ml=False
        assert signal.dynamic_levels == BUY_LEVELS
        assert signal.timestamp == valid_1h_ohlcv.index[-1].to_pydatetime()

    @pytest.mark.asyncio
    async def test_include_external_false_no_provider_calls(self, rigged_generator, valid_1h_ohlcv):
        """include_external=False → external_data همه None + provider صدا زده نشود."""
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        # تمام متدهای get_* صدا زده نشده‌اند
        for name in [
            "get_derivatives_data", "get_fundamental_data", "get_onchain_data",
            "get_order_book", "get_macro_data", "get_trending_data", "get_all_indices",
            "get_news_sentiment",
        ]:
            getattr(rigged_generator.data_provider, name).assert_not_called()

        # فیلدهای external در سیگنال None
        assert signal.fundamental_analysis is None
        assert signal.on_chain_analysis is None
        assert signal.derivatives_analysis is None
        assert signal.order_book is None
        assert signal.macro_data is None
        assert signal.trending_data is None
        assert signal.market_indices is None

    @pytest.mark.asyncio
    async def test_include_external_true_gathers_live_data(self, generator, valid_1h_ohlcv, sideways_analysis):
        """include_external=True (پیش‌فرض) → _gather_external_data صدا زده شود و
        نتایج در سیگنال قرار بگیرند."""
        generator.market_analyzer.analyze_market_condition = MagicMock(return_value=sideways_analysis)
        generator.scorer.calculate_combined_score = MagicMock(return_value=(75.0, ["buy reason"]))
        sentinel = {"derivatives": "deriv-data", "fundamental": "fund-data"}

        # configure the mocks
        generator.data_provider.get_derivatives_data = AsyncMock(return_value=sentinel["derivatives"])
        generator.data_provider.get_fundamental_data = AsyncMock(return_value=sentinel["fundamental"])
        for name in [
            "get_onchain_data", "get_order_book", "get_macro_data",
            "get_trending_data", "get_all_indices", "get_news_sentiment",
        ]:
            setattr(generator.data_provider, name, AsyncMock(return_value=None))

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await generator.generate_signal("BTC/USDT", "1h", valid_1h_ohlcv)

        generator.data_provider.get_derivatives_data.assert_awaited_once_with("BTC/USDT")
        generator.data_provider.get_fundamental_data.assert_awaited_once_with("BTC/USDT")
        assert signal.derivatives_analysis == sentinel["derivatives"]
        assert signal.fundamental_analysis == sentinel["fundamental"]

    @pytest.mark.asyncio
    async def test_include_ml_false_no_model_calls(self, rigged_generator, valid_1h_ohlcv):
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        rigged_generator.model_manager.predict_with_confidence.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_ml_true_with_predictions(self, generator, valid_1h_ohlcv, sideways_analysis, model_prediction_full):
        """include_ml=True → predict_with_confidence برای هر دو مدل صدا زده شود."""
        generator.market_analyzer.analyze_market_condition = MagicMock(return_value=sideways_analysis)
        generator.scorer.calculate_combined_score = MagicMock(return_value=(75.0, ["buy reason"]))
        generator.model_manager.predict_with_confidence = AsyncMock(return_value=model_prediction_full)

        with patch("strategy.signal_generator.detect_market_regime", return_value=NORMAL_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await generator.generate_signal("BTC/USDT", "1h", valid_1h_ohlcv, include_ml=True)

        assert generator.model_manager.predict_with_confidence.await_count == 2  # lstm + xgboost
        assert signal.ml_confidence == pytest.approx(0.75, abs=1e-3)  # 75/100


# ─── adjust_weights_by_regime Tests (gap 6) ───

class TestAdjustWeightsByRegime:
    """قاعده ۶: وزن‌دهی بر اساس رژیم بازار."""

    BASE = {
        "rsi": 10.0, "stoch": 8.0, "cci": 6.0, "williams_r": 4.0,
        "sma": 5.0, "ema": 5.0, "adx": 7.0, "supertrend": 3.0,
        "psar": 2.0, "ichimoku": 2.0, "macd": 9.0, "bb": 6.0,
    }

    def test_ranging_boosts_mean_reversion_indicators(self, generator):
        regime = RANGE_DETECT
        adjusted = generator.adjust_weights_by_regime(dict(self.BASE), regime)
        for name in ["rsi", "stoch", "cci", "williams_r"]:
            assert adjusted[name] == pytest.approx(self.BASE[name] * 1.5)
        for name in ["sma", "ema", "adx", "supertrend", "psar", "ichimoku", "macd", "bb"]:
            assert adjusted[name] == pytest.approx(self.BASE[name])

    def test_trending_boosts_trend_indicators(self, generator):
        regime = TREND_DETECT
        adjusted = generator.adjust_weights_by_regime(dict(self.BASE), regime)
        for name in ["sma", "ema", "adx", "supertrend", "psar", "ichimoku"]:
            assert adjusted[name] == pytest.approx(self.BASE[name] * 1.3)
        for name in ["rsi", "stoch", "cci", "williams_r", "macd", "bb"]:
            assert adjusted[name] == pytest.approx(self.BASE[name])

    def test_other_regimes_unchanged(self, generator):
        for market_type in ["transitional", "unknown", ""]:
            adjusted = generator.adjust_weights_by_regime(dict(self.BASE), {"market_type": market_type})
            assert adjusted == self.BASE

    def test_input_not_mutated(self, generator):
        base = dict(self.BASE)
        generator.adjust_weights_by_regime(base, RANGE_DETECT)
        assert base == self.BASE  # copy، نه mutation

    def test_missing_indicators_skipped(self, generator):
        adjusted = generator.adjust_weights_by_regime({"macd": 9.0}, RANGE_DETECT)
        assert adjusted == {"macd": 9.0}  # rsi و غیره در base نیستند → skip


# ─── _hurst_range Tests ───

class TestHurstRange:
    """_hurst_range ماپینگ Hurst بهレンジ برای threshold_regime."""

    def test_high(self):
        assert SignalGenerator._hurst_range(0.6) == "high"
        assert SignalGenerator._hurst_range(0.56) == "high"

    def test_low(self):
        assert SignalGenerator._hurst_range(0.3) == "low"
        assert SignalGenerator._hurst_range(0.44) == "low"

    def test_mid(self):
        assert SignalGenerator._hurst_range(0.5) == "mid"
        assert SignalGenerator._hurst_range(0.45) == "mid"
        assert SignalGenerator._hurst_range(0.55) == "mid"

    def test_invalid_inputs(self):
        assert SignalGenerator._hurst_range(None) == "unknown"
        assert SignalGenerator._hurst_range("abc") == "unknown"
        # NaN comparison always fails; NaN != NaN in Python. The function returns "mid" for NaN input.
        assert SignalGenerator._hurst_range(float("nan")) == "mid"


# ─── Combined Weights Tests ───

class TestCombinedWeights:
    """combined_weights = regime_weight × decorr_weight (محصوله دو مرحله)."""

    @pytest.mark.asyncio
    async def test_combined_is_product_of_regime_and_decorr(self, rigged_generator, valid_1h_ohlcv, sideways_analysis):
        """وزن نهایی محصول وزن رژیمی و وزن ضدهمبستگی است."""
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["reason"])

        # decorrelation weights کنترل‌شده
        rigged_generator.feature_engineer.get_decorrelation_weights = MagicMock(
            return_value={"rsi": 0.8, "macd": 1.2}
        )

        # base_weights از config (پیش‌فرض {} → combined همه 1.0)
        # به جای آن regime صریح patch می‌کنیم
        with patch("strategy.signal_generator.detect_market_regime", return_value=RANGE_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            # get_indicator_weights پیش‌فرض {} → base_weights خالی
            # بنابراین regime_weights هم خالی → combined هم خالی
            # تست محض قرارداد: اگر base_weights داشته باشد، combined = regime × decorr
            # برای تست واقعی نیاز به base_weights غیرخالی داریم
            rigged_generator.config_manager.get_indicator_weights = MagicMock(
                return_value={"rsi": 10.0, "macd": 8.0}
            )
            rigged_generator.scorer.score_technical_results = MagicMock(return_value=50.0)

            await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

            # score_technical_results با weights فراخوانی شده
            call_args = rigged_generator.scorer.score_technical_results.call_args
            passed_weights = call_args.kwargs.get("weights", {})
            # rsi: base 10 × regime 1.5 × decorr 0.8 = 12.0
            # macd: base 8 × regime 1.0 × decorr 1.2 = 9.6
            assert passed_weights.get("rsi") == pytest.approx(12.0)
            assert passed_weights.get("macd") == pytest.approx(9.6)


# ─── Threshold Regime Contract Tests ───

class TestThresholdRegimeContract:
    """قرارداد: threshold_regime = f"{vol_regime}|{hurst_range}" — چون
    BacktestingEngine._flush_calibration با partition("|") تجزیه می‌کند."""

    @pytest.mark.asyncio
    async def test_threshold_regime_format_pipe_separated(self, rigged_generator, valid_1h_ohlcv):
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        # volatility_regime = "high" از detect_market_regime
        # hurst_exponent = 0.5 (از sideways fixture) → "mid"
        with patch("strategy.signal_generator.detect_market_regime", return_value=TREND_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        # threshold_regime باید "high|mid" باشد
        assert signal.threshold_regime == "high|mid"
        assert signal.threshold_regime.count("|") == 1

        # BacktestingEngine contract: partition("|") باید دقیقا دو بخش بدهد
        vol, _, hurst = signal.threshold_regime.partition("|")
        assert vol == "high"
        assert hurst == "mid"
        assert "" not in (vol, hurst)  # هیچ بخش خالی نیست

    @pytest.mark.asyncio
    async def test_threshold_used_equals_optimal_threshold(self, rigged_generator, valid_1h_ohlcv):
        """threshold_used باید دقیقا مقدار برگردانده شده از
        threshold_manager.get_optimal_threshold باشد."""
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=TREND_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        # AdaptiveThresholdManager با history خالی → base_threshold (=50) برگردانده شده
        assert signal.threshold_used == 50.0

    @pytest.mark.asyncio
    async def test_threshold_regime_with_low_vol_low_hurst(self, rigged_generator, valid_1h_ohlcv, market_analysis_hurst_low):
        rigged_generator.market_analyzer.analyze_market_condition = MagicMock(
            return_value=MarketAnalysis(**market_analysis_hurst_low)
        )
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        # volatility_regime = "low", hurst = 0.3 → "low"
        with patch("strategy.signal_generator.detect_market_regime", return_value=RANGE_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        assert signal.threshold_regime == "low|low"
        vol, _, hurst = signal.threshold_regime.partition("|")
        assert vol == "low" and hurst == "low"

    @pytest.mark.asyncio
    async def test_threshold_regime_with_high_vol_high_hurst(self, rigged_generator, valid_1h_ohlcv, market_analysis_hurst_high):
        rigged_generator.market_analyzer.analyze_market_condition = MagicMock(
            return_value=MarketAnalysis(**market_analysis_hurst_high)
        )
        rigged_generator.scorer.calculate_combined_score.return_value = (75.0, ["buy reason"])

        with patch("strategy.signal_generator.detect_market_regime", return_value=TREND_DETECT), \
             patch("strategy.signal_generator.calculate_dynamic_levels", return_value=BUY_LEVELS):
            signal = await rigged_generator.generate_signal(
                "BTC/USDT", "1h", valid_1h_ohlcv, include_external=False, include_ml=False
            )

        assert signal.threshold_regime == "high|high"


# ─── _gather_external_data Contract Tests ───

EXTERNAL_KEY_TO_METHOD = {
    "derivatives": "get_derivatives_data",
    "fundamental": "get_fundamental_data",
    "onchain": "get_onchain_data",
    "order_book": "get_order_book",
    "macro": "get_macro_data",
    "trending": "get_trending_data",
    "market_indices": "get_all_indices",
    "news": "get_news_sentiment",
}


class TestGatherExternalData:
    """_gather_external_data: ۷ فراخوانی موازی + news؛ هر کدام excepción → None
    برای همان کلید (contract gap 30 در سطح SignalGenerator)."""

    @pytest.mark.asyncio
    async def test_all_sources_returned(self, generator):
        sentinels = {
            "derivatives": "deriv", "fundamental": "fund", "onchain": "onchain",
            "order_book": "ob", "macro": "macro", "trending": "trend",
            "market_indices": "indices", "news": "news",
        }
        for key, method in EXTERNAL_KEY_TO_METHOD.items():
            setattr(
                generator.data_provider, method, AsyncMock(return_value=sentinels[key])
            )

        result = await generator._gather_external_data("BTC/USDT")

        assert set(result.keys()) == set(sentinels.keys())
        for k, v in sentinels.items():
            assert result[k] == v
        # news با base_currency از split شدن symbol صدا زده می‌شود (BTC/USDT → ["BTC"])
        generator.data_provider.get_news_sentiment.assert_awaited_once_with(["BTC"])

    @pytest.mark.asyncio
    async def test_exception_per_key_becomes_none(self, generator):
        generator.data_provider.get_derivatives_data = AsyncMock(side_effect=RuntimeError("down"))
        generator.data_provider.get_fundamental_data = AsyncMock(return_value="fund")
        for key in ["onchain", "order_book", "macro", "trending", "market_indices"]:
            setattr(
                generator.data_provider,
                EXTERNAL_KEY_TO_METHOD[key],
                AsyncMock(return_value="ok"),
            )
        generator.data_provider.get_news_sentiment = AsyncMock(return_value="news")

        result = await generator._gather_external_data("BTC/USDT")

        assert result["derivatives"] is None
        assert result["fundamental"] == "fund"
        assert result["onchain"] == "ok"

    @pytest.mark.asyncio
    async def test_news_sentiment_exception_becomes_none(self, generator):
        for key in ["derivatives", "fundamental", "onchain", "order_book", "macro", "trending", "market_indices"]:
            setattr(
                generator.data_provider,
                EXTERNAL_KEY_TO_METHOD[key],
                AsyncMock(return_value="ok"),
            )
        generator.data_provider.get_news_sentiment = AsyncMock(side_effect=RuntimeError("news down"))

        result = await generator._gather_external_data("BTC/USDT")

        assert result["news"] is None
        for k in ["derivatives", "fundamental", "onchain", "order_book", "macro", "trending", "market_indices"]:
            assert result[k] == "ok"


# ─── Market Regime Tests (فاز ۱۲ — common/utils.py::detect_market_regime) ───

class TestMarketRegime:
    """قاعده ۶/۱۲: کلیدهای خروجی detect_market_regime دقیقا همان چیزی است که
    adjust_weights_by_regime (market_type) و مسیر آستانه (volatility_regime)
    در SignalGenerator می‌خوانند.

    Regression P1: قبل از اصلاح کد، import نسبی «..» داخل این تابع همیشه
    شکست می‌خورد → bare except آن را می‌خورد → hurst هرگز bind نمی‌شد →
    UnboundLocalError در سطر return → کل مسیر زنده generate_signal کرش
    می‌کرد. تست اول با نسخه قبل از اصلاح fail می‌شود (مدرک)، حالا پاس است.
    """

    def test_returns_all_required_keys(self, valid_1h_ohlcv):
        regime = detect_market_regime(valid_1h_ohlcv)
        assert set(regime.keys()) == {
            "market_type", "adx", "volatility", "volatility_regime",
            "trend_persistence", "hurst_exponent", "recommended_strategy",
        }

    def test_never_raises_unboundlocal_on_live_path(self, valid_1h_ohlcv):
        """Regression باگ UnboundLocalError — نباید Exception بدهد."""
        regime = detect_market_regime(valid_1h_ohlcv)  # قبل از اصلاح: UnboundLocalError
        assert isinstance(regime, dict)

    def test_default_lookback_hurst_is_none_not_crash(self, valid_1h_ohlcv):
        """lookback=50 < حداقل داده hurst (100) → hurst=None و
        trend_persistence="unknown" — مسیر fallback سالم، نه کرش."""
        regime = detect_market_regime(valid_1h_ohlcv)
        assert regime["hurst_exponent"] is None
        assert regime["trend_persistence"] == "unknown"

    def test_output_feeds_adjust_weights_by_regime(self, generator, valid_1h_ohlcv):
        """خروجی واقعی detect_market_regime مستقیم به‌عنوان ورودی
        adjust_weights_by_regime مصرف می‌شود (قاعده ۶) — بدون هیچ transform."""
        for lookback in (50, 150):
            regime = detect_market_regime(valid_1h_ohlcv, lookback=lookback)
            assert regime["market_type"] in ("trending", "ranging", "transitional")
            assert regime["volatility_regime"] in ("high", "low", "normal")
            adjusted = generator.adjust_weights_by_regime(
                {"rsi": 2.0, "sma": 2.0}, regime
            )
            if regime["market_type"] == "ranging":
                assert adjusted["rsi"] == pytest.approx(3.0)
                assert adjusted["sma"] == pytest.approx(2.0)
            elif regime["market_type"] == "trending":
                assert adjusted["sma"] == pytest.approx(2.6)
                assert adjusted["rsi"] == pytest.approx(2.0)
            else:
                assert adjusted == {"rsi": 2.0, "sma": 2.0}

    def test_volatility_regime_safe_for_threshold_key(self, valid_1h_ohlcv):
        """volatility_regime همان جزء اول threshold_regime در generate_signal
        است (فرمت "vol|hurst" — قرارداد BacktestingEngine._flush_calibration)؛
        نباید خودش '|' داشته باشد."""
        regime = detect_market_regime(valid_1h_ohlcv, lookback=150)
        vol = str(regime.get("volatility_regime", "normal"))
        assert "|" not in vol
        assert vol in ("high", "low", "normal")