from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from common.constants import AnalysisComponent
from common.core import (
    MarketAnalysis,
    TrendDirection,
    DerivativesAnalysis,
    IndicatorResult,
)
from config.logger import logger
from config.settings import ConfigManager


class AnalysisScorer:
    """
    A class dedicated to scoring different aspects of the market analysis.
    """

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def score_technical_results(
        self,
        processed_results: Dict[str, Any],
        market_context: MarketAnalysis,
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Calculates a score based on technical indicators.
        weights (نام → وزن، مثلاً ترکیب regime×decorrelation از SignalGenerator)
        اختیاری است؛ بدون آن میانگین ساده قبلی حفظ می‌شود.
        """
        total_score = 0.0
        total_weight = 0.0
        for name, item in processed_results.items():
            result = item.get("result")
            if (
                not result
                or not hasattr(result, "value")
                or result.value is None
            ):
                continue
            try:
                if np.isnan(result.value):
                    continue
            except (TypeError, ValueError):
                continue

            score = self.get_indicator_score(result, market_context)
            w = float(weights.get(name, 1.0)) if weights else 1.0
            total_score += score * w
            total_weight += w

        return (total_score / total_weight) if total_weight > 0 else 0.0

    def get_indicator_score(
        self, result: IndicatorResult, market_context: MarketAnalysis
    ) -> float:
        strength = (
            np.clip(result.signal_strength / 100.0, 0, 1)
            if result.signal_strength is not None
            else 0.5
        )

        bullish_keywords = [
            "bullish",
            "oversold",
            "above",
            "buy",
            "up",
            "positive",
            "accumulation",
            "uptrend",
            "support",
            "strong_buying",
        ]
        bearish_keywords = [
            "bearish",
            "overbought",
            "below",
            "sell",
            "down",
            "negative",
            "distribution",
            "downtrend",
            "resistance",
            "strong_selling",
        ]

        interpretation = result.interpretation.lower()

        direction = 0
        is_bullish = any(keyword in interpretation for keyword in bullish_keywords)
        is_bearish = any(keyword in interpretation for keyword in bearish_keywords)

        if is_bullish and not is_bearish:
            direction = 1
        elif is_bearish and not is_bullish:
            direction = -1

        base_score = direction * strength

        # Contextual adjustment
        if (
            market_context.trend == TrendDirection.BULLISH
            and "strong" in market_context.trend_strength.value
        ):
            if direction < 0 and "oversold" not in interpretation:
                base_score *= 0.5  # Penalize bearish signals in a strong uptrend
        elif (
            market_context.trend == TrendDirection.BEARISH
            and "strong" in market_context.trend_strength.value
        ):
            if direction > 0 and "overbought" not in interpretation:
                base_score *= 0.5  # Penalize bullish signals in a strong downtrend

        return base_score

    def score_market_context(self, context: MarketAnalysis) -> Tuple[float, List[str]]:
        """
        Scores the overall market context.
        قرارداد MarketAnalysis (شکاف ۸): trend/trend_strength/market_condition/
        volume_trend_score هسته امتیاز هستند (فرمول قبلی بدون تغییر)؛ بقیه
        خروجی‌های MarketConditionAnalyzer به‌عنوان تعدیل‌های محدود (±) اثر
        می‌گذارند. support/resistance در scoring مصرف نمی‌شوند چون ورودی
        calculate_dynamic_levels هستند (مصرف‌شان در ساخت Signal است، نه امتیاز).
        detect_divergence ابزار کمکی داخلی است، جزو قرارداد نیست.
        """
        score = 0.0
        reasons = []

        trend_map = {
            TrendDirection.BULLISH: 1.0,
            TrendDirection.BEARISH: -1.0,
            TrendDirection.SIDEWAYS: 0.0,
        }
        score += trend_map.get(context.trend, 0.0)
        reasons.append(f"Trend: {context.trend.value}")

        strength_map = {"strong": 1.0, "moderate": 0.5, "weak": 0.1}
        score *= strength_map.get(context.trend_strength.value, 0.5)

        if context.market_condition.value == "oversold":
            score += 0.5
        elif context.market_condition.value == "overbought":
            score -= 0.5
        reasons.append(f"Condition: {context.market_condition.value}")

        volume_score = (
            context.volume_trend_score
            if hasattr(context, "volume_trend_score")
            and context.volume_trend_score is not None
            else 0.0
        )
        score += volume_score
        reasons.append(f"Volume Score: {volume_score:.2f}")

        # Normalize the base score exactly as before
        base_score = np.clip(score / 2.0, -1.0, 1.0)

        # تعدیل‌های محدود از سایر خروجی‌های قرارداد (هر کدام مستقل و امن)
        extras = 0.0

        try:
            mom = float(context.momentum_score or 0.0)
            if mom != 0.0 and context.trend != TrendDirection.SIDEWAYS:
                aligned = (mom > 0) == (context.trend == TrendDirection.BULLISH)
                extras += 0.2 if aligned else -0.2
                reasons.append(f"Momentum {'aligned' if aligned else 'diverged'} ({mom:.2f})")
        except (TypeError, ValueError):
            pass

        try:
            vol = float(context.volatility or 0.0)
            if vol > 8.0:
                extras += -0.2
                reasons.append(f"Extreme volatility: {vol:.2f}% (-0.20)")
        except (TypeError, ValueError):
            pass

        try:
            hurst = context.hurst_exponent
            if hurst is not None:
                hurst_f = float(hurst)
                if hurst_f > 0.55 and context.trend != TrendDirection.SIDEWAYS:
                    extras += 0.15
                    reasons.append(f"Hurst persistent: {hurst_f:.2f} (+0.15)")
                elif hurst_f < 0.45:
                    if context.trend == TrendDirection.SIDEWAYS:
                        extras += 0.1
                        reasons.append(f"Hurst mean-reverting in range: {hurst_f:.2f} (+0.10)")
                    else:
                        extras += -0.1
                        reasons.append(f"Hurst mean-reverting vs trend: {hurst_f:.2f} (-0.10)")
        except (TypeError, ValueError):
            pass

        try:
            adx_v = context.adx
            if adx_v is not None:
                adx_f = float(adx_v)
                if adx_f > 25:
                    extras += 0.15
                    reasons.append(f"ADX strong: {adx_f:.1f} (+0.15)")
                elif adx_f < 15:
                    extras += -0.1
                    reasons.append(f"ADX weak: {adx_f:.1f} (-0.10)")
        except (TypeError, ValueError):
            pass

        try:
            accel = float(context.trend_acceleration or 0.0)
            if accel != 0.0 and context.trend != TrendDirection.SIDEWAYS:
                aligned = (accel > 0) == (context.trend == TrendDirection.BULLISH)
                extras += 0.1 if aligned else -0.1
                reasons.append(f"Trend acceleration {'aligned' if aligned else 'against'} ({accel:.2f})")
        except (TypeError, ValueError):
            pass

        try:
            patterns = context.candle_patterns or []
            bull = sum(1 for p in patterns if "(bullish)" in str(p))
            bear = sum(1 for p in patterns if "(bearish)" in str(p))
            net = bull - bear
            if net != 0:
                tilt = float(np.clip(net * 0.05, -0.15, 0.15))
                extras += tilt
                reasons.append(f"Candle patterns: {bull} bull / {bear} bear ({tilt:+.2f})")
        except (TypeError, ValueError):
            pass

        try:
            if bool(getattr(context, "volume_confirmation", False)):
                extras += 0.1
                reasons.append("Volume confirms trend (+0.10)")
        except (TypeError, ValueError):
            pass

        final_score = base_score + float(np.clip(extras, -0.5, 0.5)) * 0.5
        return np.clip(final_score, -1.0, 1.0), reasons

    @staticmethod
    def _unwrap(value: Any) -> Any:
        """قرارداد واحد: مقادیر external_data خام هستند (آبجکت دامنه یا dict).
        این متد فقط قالب قدیمی {"data": obj} را هم می‌پذیرد تا سازگاری
        گذشته حفظ شود؛ ساختار موازی جدیدی تعریف نمی‌کند."""
        if isinstance(value, dict) and "data" in value and len(value) == 1:
            return value["data"]
        return value

    def score_external_data(
        self, data: Dict[str, Any], market_context: MarketAnalysis, symbol: str
    ) -> Tuple[float, List[str]]:
        """
        زنجیره واحد (شکاف ۳):
            MarketDataProvider (DerivativesAnalysis و...) → SignalGenerator
            (ذخیره خام در external_data) → این متد (خوانش خام).
        هیچ Adapter موازی برای یک داده وجود ندارد.
        همه منابع جمع‌شده (شکاف ۴ و ۵: Fundamental، On-chain، OrderBook،
        Macro، Trending، MarketIndices) در امتیاز/دلایل اثر می‌گذارند.
        """
        score = 0.0
        reasons = []
        base_asset = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()

        # 1) News / Sentiment (CryptoPanic + Alternative.me + CoinDesk + Messari
        #    که داخل NewsFetcher تجمیع شده‌اند)
        try:
            news_raw = self._unwrap(data.get("news"))
            if isinstance(news_raw, dict):
                news_score = news_raw.get("score", news_raw.get("overall_score"))
                if news_score is not None:
                    score += np.clip(float(news_score) / 10.0, -0.5, 0.5)
                    reasons.append(f"News Sentiment: {float(news_score):.2f}")
                fg = news_raw.get("fear_greed_index")
                try:
                    fg_val = float(fg) if fg is not None else None
                except (TypeError, ValueError):
                    fg_val = None
                if fg_val is not None:
                    if fg_val >= 75:
                        score += -0.15
                        reasons.append(f"Fear&Greed: {fg_val:.0f} (extreme greed, contrarian -0.15)")
                    elif fg_val <= 25:
                        score += 0.15
                        reasons.append(f"Fear&Greed: {fg_val:.0f} (extreme fear, contrarian +0.15)")
        except Exception as e:
            logger.debug(f"News scoring skipped: {e}")

        # 2) Derivatives (Binance)
        try:
            deriv = self._unwrap(data.get("derivatives"))
            if deriv is not None and not isinstance(deriv, dict):
                if getattr(deriv, "funding_rate", None) is not None:
                    funding_score = self.normalize_funding_rate(
                        deriv.funding_rate, symbol, market_context
                    )
                    score += funding_score
                    reasons.append(
                        f"Funding Rate: {deriv.funding_rate:.4f} (Score: {funding_score:.2f})"
                    )
                ratio = getattr(deriv, "taker_long_short_ratio", None)
                if ratio is not None:
                    ratio_score = 0.2 if ratio > 1.1 else -0.2 if ratio < 0.9 else 0.0
                    score += ratio_score
                    reasons.append(
                        f"Taker L/S Ratio: {ratio:.2f} (Score: {ratio_score:.2f})"
                    )
        except Exception as e:
            logger.debug(f"Derivatives scoring skipped: {e}")

        # 3) Fundamental (CoinGecko)
        try:
            fund = self._unwrap(data.get("fundamental"))
            if fund is not None and not isinstance(fund, dict):
                dev = float(getattr(fund, "developer_score", 0) or 0)
                comm = float(getattr(fund, "community_score", 0) or 0)
                if dev > 0 or comm > 0:
                    score += 0.1
                    reasons.append(
                        f"Fundamental: dev {dev:.1f} / community {comm:.0f} (+0.10)"
                    )
        except Exception as e:
            logger.debug(f"Fundamental scoring skipped: {e}")

        # 4) On-chain (Messari: MVRV/SOPR)
        try:
            onchain = self._unwrap(data.get("onchain"))
            if onchain is not None and not isinstance(onchain, dict):
                mvrv = getattr(onchain, "mvrv", None)
                if mvrv is not None:
                    mvrv_f = float(mvrv)
                    if mvrv_f > 3.5:
                        score += -0.2
                        reasons.append(f"On-chain MVRV: {mvrv_f:.2f} (overvalued -0.20)")
                    elif mvrv_f < 1.0:
                        score += 0.2
                        reasons.append(f"On-chain MVRV: {mvrv_f:.2f} (undervalued +0.20)")
                sopr = getattr(onchain, "sopr", None)
                if sopr is not None:
                    sopr_f = float(sopr)
                    if sopr_f > 1.05:
                        score += -0.1
                        reasons.append(f"On-chain SOPR: {sopr_f:.3f} (profit-taking -0.10)")
                    elif sopr_f < 0.98:
                        score += 0.1
                        reasons.append(f"On-chain SOPR: {sopr_f:.3f} (capitulation +0.10)")
        except Exception as e:
            logger.debug(f"On-chain scoring skipped: {e}")

        # 5) Order book imbalance (Binance)
        try:
            ob = self._unwrap(data.get("order_book"))
            if ob is not None and not isinstance(ob, dict):
                bid_v = getattr(ob, "total_bid_volume", None)
                ask_v = getattr(ob, "total_ask_volume", None)
                if bid_v and ask_v and (bid_v + ask_v) > 0:
                    imb = (float(bid_v) - float(ask_v)) / (float(bid_v) + float(ask_v))
                    if imb > 0.2:
                        score += 0.15
                        reasons.append(f"OrderBook imbalance: {imb:+.2f} (bid pressure +0.15)")
                    elif imb < -0.2:
                        score += -0.15
                        reasons.append(f"OrderBook imbalance: {imb:+.2f} (ask pressure -0.15)")
        except Exception as e:
            logger.debug(f"OrderBook scoring skipped: {e}")

        # 6) Macro (AlphaVantage)
        try:
            macro = self._unwrap(data.get("macro"))
            if macro is not None and not isinstance(macro, dict):
                fed = getattr(macro, "fed_rate", None)
                if fed is not None:
                    fed_f = float(fed)
                    if fed_f > 4.0:
                        score += -0.1
                        reasons.append(f"Macro Fed Rate: {fed_f:.2f}% (restrictive -0.10)")
                cpi = getattr(macro, "cpi", None)
                if cpi is not None:
                    cpi_f = float(cpi)
                    if cpi_f > 4.0:
                        score += -0.05
                        reasons.append(f"Macro CPI: {cpi_f:.2f}% (hot inflation -0.05)")
        except Exception as e:
            logger.debug(f"Macro scoring skipped: {e}")

        # 7) Trending (CoinGecko)
        try:
            trending = self._unwrap(data.get("trending"))
            coins: List[str] = []
            if trending is not None:
                if isinstance(trending, dict):
                    coins = trending.get("coingecko_trending", []) or []
                elif hasattr(trending, "coingecko_trending"):
                    coins = trending.coingecko_trending or []
            if any(str(c).upper() == base_asset for c in coins):
                score += 0.1
                reasons.append(f"Trending: {base_asset} is trending (+0.10)")
        except Exception as e:
            logger.debug(f"Trending scoring skipped: {e}")

        # 8) Market indices (CoinGecko + DeFiLlama + YFinance + AlphaVantage
        #    که داخل MarketIndicesFetcher تجمیع شده‌اند)
        try:
            indices = self._unwrap(data.get("market_indices"))
            if isinstance(indices, dict) and indices:
                btc_d = indices.get("BTC.D")
                if isinstance(btc_d, (int, float)) and base_asset != "BTC":
                    if float(btc_d) > 60:
                        score += -0.05
                        reasons.append(f"BTC dominance: {float(btc_d):.1f}% (alt headwind -0.05)")
                usdt_d = indices.get("USDT.D")
                if isinstance(usdt_d, (int, float)) and float(usdt_d) > 8:
                    score += -0.05
                    reasons.append(f"USDT dominance: {float(usdt_d):.1f}% (risk-off -0.05)")
                dxy = indices.get("DXY")
                if isinstance(dxy, (int, float)) and float(dxy) > 105:
                    score += -0.1
                    reasons.append(f"DXY: {float(dxy):.1f} (strong dollar -0.10)")
                vix = indices.get("VIX")
                if isinstance(vix, (int, float)) and float(vix) > 30:
                    score += -0.1
                    reasons.append(f"VIX: {float(vix):.1f} (fear -0.10)")
                tvl = indices.get("DEFI_TVL")
                if isinstance(tvl, (int, float)) and float(tvl) > 0:
                    reasons.append("DeFi TVL available (liquidity context)")
        except Exception as e:
            logger.debug(f"Market-indices scoring skipped: {e}")

        return np.clip(score, -1.0, 1.0), reasons

    def normalize_funding_rate(
        self, funding_rate: float, symbol: str, market_context: MarketAnalysis
    ) -> float:
        """
        Normalizes funding rate into a score from -0.3 to 0.3.
        Negative funding is generally bullish, positive is bearish.
        """
        asset = symbol.split("/")[0]
        # These are just example averages, could be dynamically calculated
        market_avg_funding = {"BTC": 0.01, "ETH": 0.008, "default": 0.02}.get(
            asset, 0.02
        )

        # High funding rate is bearish, so score is negative
        if funding_rate > market_avg_funding * 2:
            return -0.3
        if funding_rate > market_avg_funding:
            return -0.15
        # Negative funding rate is bullish, so score is positive
        if funding_rate < -market_avg_funding:
            return 0.3
        if funding_rate < 0:
            return 0.15

        return 0.0

    def score_ml_predictions(
        self, predictions: Dict[str, Dict[str, float]], current_price: float
    ) -> Tuple[float, List[str], float]:
        """
        Scores predictions from machine learning models.
        """
        if not predictions:
            return 0.0, [], 0.0

        weighted_score = 0.0
        total_confidence = 0.0
        reasons = []

        model_weights = {"lstm": 0.6, "xgboost": 0.4}

        for model_name, pred_data in predictions.items():
            pred_price = pred_data.get("prediction", 0)
            confidence = pred_data.get(
                "calibrated_confidence", pred_data.get("confidence", 0)
            )

            if pred_price == 0:
                continue

            direction = 1 if pred_price > current_price else -1

            # Weight the score by the model's confidence and its predefined weight
            model_weight = model_weights.get(model_name, 0.5)
            weighted_score += direction * (confidence / 100.0) * model_weight
            total_confidence += confidence * model_weight

            reasons.append(
                f"ML ({model_name}): Predicts {'increase' if direction > 0 else 'decrease'} (Conf: {confidence:.1f}%)"
            )

        # Normalize the score by the total confidence to get a value between -1 and 1
        num_models = len(predictions)
        if num_models == 0:
            return 0.0, [], 0.0

        total_model_weights = sum(model_weights.get(m, 0.5) for m in predictions)
        if total_model_weights == 0:
            return 0.0, [], 0.0

        final_score = weighted_score / total_model_weights
        avg_confidence = total_confidence / total_model_weights

        return np.clip(final_score, -1.0, 1.0), reasons, avg_confidence / 100.0

    def calculate_combined_score(
        self,
        scores: Dict[AnalysisComponent, float],
        reasons: List[str],
        timeframe: str,
    ) -> Tuple[float, List[str]]:
        """
        Combines scores from all analysis parts into a single final score.
        """
        weights = self.config_manager.get_component_weights(timeframe)

        final_score = 0.0
        total_weight = 0.0

        for component, score in scores.items():
            weight = weights.get(component.value, 0)
            final_score += score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0, reasons

        # Normalize and scale to -100 to 100 range
        normalized_score = (final_score / total_weight) * 100
        return normalized_score, reasons
