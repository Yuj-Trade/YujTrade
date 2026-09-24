import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import pandas as pd

from common.core import TradingSignal, SignalType
from data.data_provider import MarketDataProvider
from data.data_validator import DataQualityChecker
from features.feature_engineering import FeatureEngineer
from analysis.market_analyzer import MarketConditionAnalyzer
from analysis.scoring import AnalysisScorer
from modeling.model_manager import ModelManager
from config.settings import ConfigManager
from config.logger import logger
from common.utils import (
    calculate_risk_reward_ratio,
    calculate_dynamic_levels,
    detect_market_regime,
)
from common.constants import LONG_TERM_CONFIG, AnalysisComponent


class SignalGenerator:
    def __init__(
        self,
        data_provider: MarketDataProvider,
        model_manager: ModelManager,
        config_manager: ConfigManager,
    ):
        self.data_provider = data_provider
        self.model_manager = model_manager
        self.config_manager = config_manager

        self.feature_engineer = FeatureEngineer(self.config_manager)
        self.market_analyzer = MarketConditionAnalyzer()
        self.scorer = AnalysisScorer(self.config_manager)
        self.data_validator = DataQualityChecker()

    async def generate_signal(
        self,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame,
        include_external: bool = True,
        include_ml: bool = True,
    ) -> Optional[TradingSignal]:
        """include_external/include_ml: برای بک‌تست تاریخی False می‌شوند تا
        داده لحظه‌ای (live) وارد تحلیل گذشته نشود (شکاف ۱۴). تولید زنده
        همیشه True است و رفتار آن بدون تغییر می‌ماند."""
        analysis_timestamp = datetime.now(timezone.utc)

        is_valid, quality_msg = self.data_validator.validate_data_quality(
            data, timeframe
        )
        if not is_valid:
            logger.warning(
                f"Data quality check failed for {symbol}-{timeframe}: {quality_msg}"
            )
            return None

        market_regime = detect_market_regime(data)
        market_context = self.market_analyzer.analyze_market_condition(data)

        last_indicator_results = self.feature_engineer.get_last_indicator_results(
            data, timeframe
        )

        # شکاف ۶: Market Data → Market Regime → Existing Weight Adjustment → Scoring
        base_weights = self.config_manager.get_indicator_weights(timeframe) or {}
        regime_weights = self.adjust_weights_by_regime(
            dict(base_weights), market_regime
        )
        decorr_weights = self.feature_engineer.get_decorrelation_weights(
            last_indicator_results
        )
        combined_weights = {
            name: float(regime_weights.get(name, 1.0))
            * float(decorr_weights.get(name, 1.0))
            for name in last_indicator_results.keys()
        }

        tech_score = self.scorer.score_technical_results(
            last_indicator_results, market_context, weights=combined_weights
        )

        market_score, market_reasons = self.scorer.score_market_context(market_context)

        if include_external:
            external_data = await self._gather_external_data(symbol)
        else:
            external_data = {
                "derivatives": None,
                "fundamental": None,
                "onchain": None,
                "order_book": None,
                "macro": None,
                "trending": None,
                "market_indices": None,
                "news": None,
            }
        external_score, external_reasons = self.scorer.score_external_data(
            external_data, market_context, symbol
        )

        current_price = data["close"].iloc[-1]
        if include_ml:
            ml_predictions = await self.get_ml_predictions(symbol, timeframe)
        else:
            ml_predictions = {}
        ml_score, ml_reasons, ml_confidence = self.scorer.score_ml_predictions(
            ml_predictions, current_price
        )

        scores = {
            AnalysisComponent.TECHNICAL_ANALYSIS: tech_score,
            AnalysisComponent.MARKET_CONTEXT: market_score,
            AnalysisComponent.EXTERNAL_DATA: external_score,
            AnalysisComponent.ML_MODELS: ml_score,
        }
        all_reasons = market_reasons + external_reasons + ml_reasons
        final_score, all_reasons = self.scorer.calculate_combined_score(
            scores, all_reasons, timeframe
        )

        signal_type = self.determine_signal_type(final_score)
        if signal_type == SignalType.HOLD:
            logger.info(
                f"No signal for {symbol}-{timeframe}. Final Score: {final_score:.2f}"
            )
            return None

        levels = calculate_dynamic_levels(
            data, signal_type, market_context, external_data.get("order_book")
        )
        rr_ratio = calculate_risk_reward_ratio(
            levels["primary_entry"],
            levels["tight_stop"],
            levels["primary_exit"],
            signal_type,
        )

        min_rr_ratio = LONG_TERM_CONFIG.get("min_risk_reward_ratio", 2.0)
        if rr_ratio < min_rr_ratio:
            logger.info(
                f"Risk/Reward {rr_ratio:.2f} below minimum {min_rr_ratio} for {symbol}-{timeframe}"
            )
            return None

        signal = TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            entry_price=levels["primary_entry"],
            exit_price=levels["primary_exit"],
            stop_loss=levels["tight_stop"],
            timestamp=data.index[-1].to_pydatetime(),
            timeframe=timeframe,
            confidence_score=abs(final_score),
            reasons=all_reasons,
            risk_reward_ratio=rr_ratio,
            predicted_profit=abs(levels["primary_exit"] - levels["primary_entry"]),
            volume_analysis={
                "volume_trend": market_context.volume_trend,
                "volume_ratio": market_context.volume_ratio,
            },
            market_context=market_context.__dict__,
            dynamic_levels=levels,
            analysis_timestamp=analysis_timestamp,
            fundamental_analysis=external_data.get("fundamental"),
            on_chain_analysis=external_data.get("onchain"),
            derivatives_analysis=external_data.get("derivatives"),
            order_book=external_data.get("order_book"),
            macro_data=external_data.get("macro"),
            trending_data=external_data.get("trending"),
            market_indices=external_data.get("market_indices"),
            ml_confidence=float(ml_confidence),
        )

        return signal

    async def _gather_external_data(self, symbol: str) -> Dict[str, Any]:
        tasks = {
            "derivatives": self.data_provider.get_derivatives_data(symbol),
            "fundamental": self.data_provider.get_fundamental_data(symbol),
            "onchain": self.data_provider.get_onchain_data(symbol),
            "order_book": self.data_provider.get_order_book(symbol),
            "macro": self.data_provider.get_macro_data(),
            "trending": self.data_provider.get_trending_data(),
            # get_all_indices = crypto (CoinGecko+DeFiLlama) + traditional
            # (YFinance: DXY/SPX/VIX/...) + macro تا همه Sourceها در زنجیره باشند.
            "market_indices": self.data_provider.get_all_indices(),
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        external_data = {}
        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch {key} for {symbol}: {result}")
                external_data[key] = None
            else:
                external_data[key] = result

        try:
            base_currency = symbol.split("/")[0]
            news_sentiment = await self.data_provider.get_news_sentiment(
                [base_currency]
            )
            # قرارداد واحد: همه مقادیر external_data خام ذخیره می‌شوند
            # (بدون wrapper موازی {"data": ...})؛ Scorer هم همان را می‌خواند.
            external_data["news"] = news_sentiment
        except Exception as e:
            logger.warning(f"Failed to fetch news sentiment for {symbol}: {e}")
            external_data["news"] = None

        return external_data

    async def get_ml_predictions(self, symbol: str, timeframe: str) -> Dict[str, Dict]:
        predictions = {}
        model_types = ["lstm", "xgboost"]
        tasks = [
            self.model_manager.predict_with_confidence(m_type, symbol, timeframe)
            for m_type in model_types
        ]
        results = await asyncio.gather(*tasks)
        for i, res in enumerate(results):
            if res:
                predictions[model_types[i]] = res
        return predictions

    def determine_signal_type(self, score: float) -> SignalType:
        threshold = self.config_manager.get("signal_threshold", 50)
        if score > threshold:
            return SignalType.BUY
        if score < -threshold:
            return SignalType.SELL
        return SignalType.HOLD

    def adjust_weights_by_regime(
        self, base_weights: Dict[str, float], market_regime: Dict[str, Any]
    ) -> Dict[str, float]:
        adjusted = base_weights.copy()

        if market_regime.get("market_type") == "ranging":
            mean_reversion_indicators = ["rsi", "stoch", "cci", "williams_r"]
            for indicator in mean_reversion_indicators:
                if indicator in adjusted:
                    adjusted[indicator] *= 1.5
        elif market_regime.get("market_type") == "trending":
            trend_indicators = ["sma", "ema", "adx", "supertrend", "psar", "ichimoku"]
            for indicator in trend_indicators:
                if indicator in adjusted:
                    adjusted[indicator] *= 1.3

        return adjusted