import asyncio
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from analysis.market_analyzer import MarketConditionAnalyzer
from analysis.scoring import AnalysisScorer
from application.decide import decide
from application.gate_config import build_gate_config
from application.snapshot import build_snapshot
from common.constants import LONG_TERM_CONFIG, AnalysisComponent
from common.core import SignalType, TradingSignal
from common.exceptions import InsufficientDataError
from common.utils import (
    calculate_dynamic_levels,
    calculate_risk_reward_ratio,
    detect_market_regime,
)
from config.logger import logger
from config.settings import ConfigManager
from data.data_provider import MarketDataProvider
from data.data_validator import DataQualityChecker
from data.warehouse import IndicatorHistoryWarehouse
from domain.gates import normalize_confidence
from domain.types import Candle, Reject
from features.feature_engineering import FeatureEngineer
from modeling.model_manager import ModelManager
from strategy.prediction_trace import PredictionTraceRecorder
from strategy.signal_tracker import AdaptiveThresholdManager, make_signal_id


def _indicator_values(indicators: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, payload in indicators.items():
        result = payload.get("result") if isinstance(payload, dict) else None
        value = getattr(result, "value", None)
        if value is None:
            values[name] = None
        elif isinstance(value, (int, float, str, bool)):
            values[name] = value
        elif hasattr(value, "tolist"):
            try:
                values[name] = value.tolist()
            except (TypeError, ValueError):
                values[name] = str(value)
        else:
            values[name] = str(value)
    return values


class SignalGenerator:
    def __init__(
        self,
        data_provider: MarketDataProvider,
        model_manager: ModelManager,
        config_manager: ConfigManager,
        trace_recorder: PredictionTraceRecorder | None = None,
    ):
        self.data_provider = data_provider
        self.model_manager = model_manager
        self.config_manager = config_manager
        self.trace_recorder = trace_recorder

        history_path = self.config_manager.get(
            "indicator_history_path", "runs/indicator_history.db"
        )
        self.feature_engineer = FeatureEngineer(
            self.config_manager, IndicatorHistoryWarehouse(history_path)
        )
        self.market_analyzer = MarketConditionAnalyzer()
        self.scorer = AnalysisScorer(self.config_manager)
        self.data_validator = DataQualityChecker()

        self.threshold_manager = AdaptiveThresholdManager()
        self._cycle_memo: dict[tuple[str, str | None], Any] | None = None
        self._cycle_reported: set[tuple[str, str | None]] | None = None

    async def begin_run_cycle(self) -> None:
        self._cycle_memo = {}
        self._cycle_reported = set()

    async def end_run_cycle(self) -> None:
        memo, self._cycle_memo = self._cycle_memo, None
        self._cycle_reported = None
        for task in (memo or {}).values():
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()

    @staticmethod
    def _hurst_range(hurst) -> str:
        try:
            h = float(hurst)
        except (TypeError, ValueError):
            return "unknown"
        if h > 0.55:
            return "high"
        if h < 0.45:
            return "low"
        return "mid"

    async def generate_signal(
        self,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame,
        include_external: bool = True,
        include_ml: bool = True,
    ) -> TradingSignal | None:
        analysis_timestamp = datetime.now(UTC)

        is_valid, quality_msg = self.data_validator.validate_data_quality(data, timeframe)
        if not is_valid:
            raise InsufficientDataError(
                f"Data quality check failed for {symbol}-{timeframe}: {quality_msg}"
            )

        market_regime = detect_market_regime(data)
        market_context = self.market_analyzer.analyze_market_condition(data)

        last_indicator_results = await self.feature_engineer.get_last_indicator_results(
            data, timeframe
        )

        base_weights = self.config_manager.get_indicator_weights(timeframe) or {}
        regime_weights = self.adjust_weights_by_regime(dict(base_weights), market_regime)
        decorr_weights = self.feature_engineer.get_decorrelation_weights(last_indicator_results)
        combined_weights = {
            name: float(regime_weights.get(name, 1.0)) * float(decorr_weights.get(name, 1.0))
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

        vol_regime = str(market_regime.get("volatility_regime", "normal"))
        hurst_range = self._hurst_range(market_context.hurst_exponent)
        base_threshold = self.config_manager.get("signal_threshold", 10)
        threshold = self.threshold_manager.get_optimal_threshold(
            vol_regime, hurst_range, base_threshold
        )
        threshold_regime = f"{vol_regime}|{hurst_range}"

        signal_type = self.determine_signal_type(final_score, threshold)
        if signal_type == SignalType.HOLD:
            logger.info(f"No signal for {symbol}-{timeframe}. Final Score: {final_score:.2f}")
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
            threshold_used=float(threshold),
            threshold_regime=threshold_regime,
        )
        signal.market_context["ml_predictions"] = ml_predictions

        candles = [
            Candle(
                timestamp=timestamp.to_pydatetime()
                if hasattr(timestamp, "to_pydatetime")
                else timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
            )
            for timestamp, row in data.tail(500).iterrows()
        ]
        gate_config = build_gate_config(self.config_manager.get, timeframe)
        decision = decide(
            build_snapshot(
                symbol,
                timeframe,
                candles,
                score=float(abs(final_score)),
                confidence=normalize_confidence(abs(final_score)),
                side=signal_type.value,
                entry=signal.entry_price,
                stop=signal.stop_loss,
                target=signal.exit_price,
                trend_strength=str(
                    getattr(market_context.trend_strength, "value", market_context.trend_strength)
                ),
                volume_surge=float(market_context.volume_ratio),
                details={"ml_predictions": ml_predictions},
            ),
            gate_config,
            min_score=float(threshold),
        )
        if isinstance(decision, Reject):
            logger.info(f"Gate rejected {symbol}-{timeframe}: {decision.reason.value}")
            return None

        await self._record_prediction_trace(
            signal,
            symbol=symbol,
            timeframe=timeframe,
            indicators=last_indicator_results,
            ml_predictions=ml_predictions,
            score=float(abs(final_score)),
            threshold=float(threshold),
        )
        return signal

    async def _record_prediction_trace(
        self,
        signal: TradingSignal,
        symbol: str,
        timeframe: str,
        indicators: dict[str, Any],
        ml_predictions: dict[str, Any],
        score: float,
        threshold: float,
    ) -> None:
        recorder = self.trace_recorder
        if recorder is None or not recorder.enabled:
            return
        moment = signal.timestamp
        signal_id = make_signal_id(symbol, timeframe, moment, signal.signal_type.value)
        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": moment.isoformat() if hasattr(moment, "isoformat") else str(moment),
            "feature_names": sorted(indicators.keys()),
            "feature_values": _indicator_values(indicators),
            "ml_predictions": ml_predictions,
            "score": score,
            "threshold_used": threshold,
        }
        await recorder.record(signal_id, payload)

    async def _gather_external_data(self, symbol: str) -> dict[str, Any]:
        base_asset = symbol.split("/")[0]
        factories = {
            "derivatives": lambda: self.data_provider.get_derivatives_data(symbol),
            "fundamental": lambda: self.data_provider.get_fundamental_data(symbol),
            "onchain": lambda: self.data_provider.get_onchain_data(symbol),
            "order_book": lambda: self.data_provider.get_order_book(symbol),
            "macro": lambda: self.data_provider.get_macro_data(),
            "trending": lambda: self.data_provider.get_trending_data(),
            "market_indices": lambda: self.data_provider.get_all_indices(),
            "news": lambda: self.data_provider.get_news_sentiment([base_asset]),
        }
        memo_scope = {
            "derivatives": symbol,
            "fundamental": symbol,
            "onchain": symbol,
            "order_book": symbol,
            "macro": None,
            "trending": None,
            "market_indices": None,
            "news": base_asset,
        }

        memo = self._cycle_memo
        tasks: dict[str, asyncio.Task] = {}
        for key, factory in factories.items():
            memo_key = (key, memo_scope[key])
            existing = memo.get(memo_key) if memo is not None else None
            if existing is not None:
                tasks[key] = existing
                continue
            task = asyncio.ensure_future(factory())
            if memo is not None:
                memo[memo_key] = task
            tasks[key] = task

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        external_data: dict[str, Any] = {}
        for key, result in zip(tasks.keys(), results, strict=False):
            if isinstance(result, Exception):
                external_data[key] = None
                self._report_external_failure(key, memo_scope[key], symbol, result)
            else:
                external_data[key] = result

        return external_data

    def _report_external_failure(
        self, key: str, scope: str | None, symbol: str, error: BaseException
    ) -> None:
        report_key = (key, scope)
        reported = self._cycle_reported
        if reported is not None:
            if report_key in reported:
                logger.debug(f"External source {key} already reported this cycle ({symbol})")
                return
            reported.add(report_key)
        logger.warning(f"Failed to fetch {key} for {symbol}: {error}")

    async def get_ml_predictions(self, symbol: str, timeframe: str) -> dict[str, dict]:
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

    def determine_signal_type(self, score: float, threshold: float = None) -> SignalType:
        if threshold is None:
            threshold = self.config_manager.get("signal_threshold", 10)
        if score > threshold:
            return SignalType.BUY
        if score < -threshold:
            return SignalType.SELL
        return SignalType.HOLD

    def adjust_weights_by_regime(
        self, base_weights: dict[str, float], market_regime: dict[str, Any]
    ) -> dict[str, float]:
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
