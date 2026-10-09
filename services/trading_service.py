import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from config.settings import ConfigManager
from common.core import TradingSignal
from data.data_provider import MarketDataProvider
from config.logger import logger
from common.constants import LONG_TERM_CONFIG, SIGNAL_EXPIRY_BY_TIMEFRAME
from strategy.signal_generator import SignalGenerator
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from strategy.signal_ranking import SignalRanking
from strategy.signal_tracker import SignalTracker, make_signal_id
from modeling.model_manager import ModelManager, ModelDataProvider
from common.exceptions import InvalidSymbolError
from utils.resource_manager import ResourceManager
from trading.risk_manager import RiskConfig, RiskManager, build_risk_config
from trading.portfolio import PortfolioManager
from trading.paper_trading import PaperTradingEngine
from trading.execution import ExchangeAdapter, ExecutionEngine


async def create_trading_stack(
    config_manager: Optional[ConfigManager] = None,
    resource_manager: Optional[ResourceManager] = None,
) -> Tuple[ConfigManager, ResourceManager, MarketDataProvider, "TradingService"]:
    """تنها Composition Root سیستم (قاعده ۱۸). MainApp، TaskServiceContainer و
    ابزارهای بهینه‌سازی همگی از همین مسیر stack را می‌سازند تا dependency
    graph دوباره‌کاری و drift نشود. خروجی: (config, resources, provider, service).
    تمیزکاری همچنان با خود فراخواننده است (provider.close /
    service.cleanup / resources.cleanup)."""
    config_manager = config_manager or ConfigManager()
    resource_manager = resource_manager or ResourceManager()

    market_data_provider = MarketDataProvider(
        resource_manager=resource_manager, config_manager=config_manager
    )
    await market_data_provider.initialize()

    trading_service = TradingService(
        market_data_provider=market_data_provider,
        config_manager=config_manager,
        resource_manager=resource_manager,
    )
    await trading_service.initialize()

    return config_manager, resource_manager, market_data_provider, trading_service


class TradingService(ModelDataProvider):
    """ترتیب واحد Quality Pipeline (قاعده ۲۱/۲۹) — بدون Rule جدید:
    1. SignalGenerator: signal_threshold + min_risk_reward_ratio
    2. MultiTimeframeAnalyzer: score ‎>= 0.3 و بدون direction_conflict
    3. _passes_quality_gates: min_confidence_threshold (per-tf) →
       min_trend_strength → min_volume_surge
    4. SignalRanking + محدودیت‌ها: ابتدا سقف هر تایم‌فریم
       (max_signals_per_timeframe، قاعده ۲۲) سپس سقف کل
       (max_signals_per_run)."""

    _TREND_STRENGTH_RANK = {"WEAK": 0, "MODERATE": 1, "STRONG": 2}
    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        config_manager: ConfigManager,
        resource_manager: ResourceManager,
    ):
        self.market_data_provider = market_data_provider
        self.config_manager = config_manager
        self.resource_manager = resource_manager
        self.invalid_symbols: Set[str] = set()
        self._initialized = False
        # شمارنده خطاهای آخرین اجرا (قاعده ۳۰): caller با آن «سیگنالی نیست»
        # را از «تحلیل شکست خورد» تشخیص می‌دهد.
        self.last_errors: int = 0

        # NOTE: ResourceManager.get_redis_client() is async؛ فراخوانی آن در
        # __init__ هم‌زمان (sync) یک coroutine برمی‌گرداند نه کلاینت.
        # برای جلوگیری از عبور coroutine به‌جای Redis، اتصال در
        # initialize() برقرار می‌شود. تا قبل از آن redis=None است.
        self._redis_client = getattr(resource_manager, "_redis_client", None)

        self.model_manager = ModelManager(
            data_provider=self,
            redis_client=self._redis_client,
            model_path=self.config_manager.get("model_path", "models"),
            auto_train_on_predict=self.config_manager.get(
                "model_auto_train_on_predict", False
            ),
        )

        self.signal_generator = SignalGenerator(
            data_provider=self.market_data_provider,
            model_manager=self.model_manager,
            config_manager=self.config_manager,
        )

        self.multi_tf_analyzer = MultiTimeframeAnalyzer(
            market_data_provider=market_data_provider,
            redis_client=self._redis_client,
            config_manager=self.config_manager,
        )
        risk_cfg = build_risk_config(self.config_manager)
        self.risk_manager = RiskManager(risk_cfg)
        self.portfolio = PortfolioManager(float(self.config_manager.get("initial_cash", 10000.0)))
        self.paper_engine = PaperTradingEngine(portfolio=self.portfolio, risk_manager=self.risk_manager)
        self.execution_engine = ExecutionEngine(adapter=ExchangeAdapter(dry_run=bool(self.config_manager.get("execution_dry_run", True))))
        self.signal_tracker = SignalTracker()

    async def initialize(self) -> None:
        """اتصال Redis را برقرار و به زیرکامپوننت‌ها تزریق می‌کند. Idempotent."""
        if self._initialized:
            return
        try:
            redis_client = await self.resource_manager.get_redis_client()
        except Exception:
            redis_client = None
        self._redis_client = redis_client
        self.model_manager.redis_client = redis_client
        self.multi_tf_analyzer.redis = redis_client
        self._initialized = True

    async def get_data_for_model(
        self, symbol: str, timeframe: str, for_prediction: bool = False
    ) -> Optional[pd.DataFrame]:
        # همان قرارداد TrainingDataProvider: محدودیت‌ها فقط از Config.
        limit_map = self.config_manager.get(
            "model_data_limits",
            {"1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300},
        )
        limit = limit_map.get(timeframe, 2000)

        if for_prediction:
            limit = min(
                limit, self.config_manager.get("model_prediction_limit", 300)
            )

        try:
            data = await self.market_data_provider.fetch_ohlcv_data(
                symbol, timeframe, limit=limit
            )
            if data is None or data.empty or len(data) < 200:
                logger.warning(
                    f"Insufficient data for model operations for {symbol}-{timeframe}."
                )
                return None
            return data
        except Exception as e:
            logger.error(
                f"Failed to fetch data for model for {symbol}-{timeframe}: {e}"
            )
            return None

    async def analyze_symbol(
        self, symbol: str, timeframe: str
    ) -> Optional[TradingSignal]:
        """قرارداد خطای واحد (قاعده ۳۰):
        - None یعنی «سیگنالی نیست» (HOLD/رد RR/رد multi-TF/رد گیت‌ها) یا
          سمبل دائماً نامعتبر (ignore-list).
        - Exception یعنی «تحلیل شکست خورد» و منتشر می‌شود تا جمع‌کننده
          (run_*‎) آن را بشمارد و گزارش دهد، نه اینکه به None تبدیل شود."""
        if symbol in self.invalid_symbols:
            logger.debug(f"Skipping analysis for invalid symbol: {symbol}")
            return None

        logger.info(f"Analyzing {symbol} on {timeframe} timeframe...")
        try:
            # همان منبع DataQualityChecker (قاعده ۲۳): LONG_TERM_CONFIG.
            min_data_points = LONG_TERM_CONFIG.get("min_data_points", {})
            limit = min_data_points.get(timeframe, 600)
            ohlcv_data = await self.market_data_provider.fetch_ohlcv_data(
                symbol, timeframe, limit=limit
            )

            if ohlcv_data is None or ohlcv_data.empty:
                logger.warning(f"No OHLCV data for {symbol}-{timeframe}")
                return None

            signal = await self.signal_generator.generate_signal(
                symbol, timeframe, ohlcv_data
            )

            if signal:
                multi_tf_score, _, direction_conflict = (
                    await self.multi_tf_analyzer.get_confirmation_score(
                        symbol, timeframe, signal.signal_type, ohlcv_data
                    )
                )
                if multi_tf_score < 0.3 or direction_conflict:
                    logger.info(
                        f"Signal for {symbol}-{timeframe} rejected due to multi-timeframe conflict."
                    )
                    return None

                if not self._passes_quality_gates(signal):
                    logger.info(
                        f"Signal for {symbol}-{timeframe} rejected by quality gates."
                    )
                    return None

                logger.info(
                    f"Generated signal for {symbol} on {timeframe}: {signal.signal_type.value} with confidence {signal.confidence_score:.2f}"
                )
                # شروع lifecycle رهگیری: generated → pending (قاعده ۱۳).
                # record الان async است — بدون await هیچ سیگنالی ذخیره
                # نمی‌شود (coroutine بدون await دور ریخته می‌شود).
                # قاعده ۴۱: created_at زمان تولید (UTC) است، نه زمان کندل؛
                # زمان کندل جدا در candle_time می‌ماند (id همچنان کندل‌محور
                # است تا پیوند Generator↔Backtest حفظ شود). stop/target هم
                # ذخیره می‌شوند تا resolve روی کندل‌ها قضاوت کند (قاعده ۴۲).
                # created_at/threshold_used/threshold_regime برای
                # reconciliation دوره‌ای و تغذیه کالیبراسیون ذخیره می‌شوند
                # (قاعده ۳۱).
                try:
                    await self.signal_tracker.record(
                        make_signal_id(
                            signal.symbol,
                            signal.timeframe,
                            signal.timestamp,
                            signal.signal_type.value,
                        ),
                        None,
                        {
                            "symbol": signal.symbol,
                            "timeframe": signal.timeframe,
                            "signal_type": signal.signal_type.value,
                            "confidence": signal.confidence_score,
                            "entry": signal.entry_price,
                            "stop": signal.stop_loss,
                            "target": signal.exit_price,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "candle_time": signal.timestamp.isoformat(),
                            "threshold_used": signal.threshold_used,
                            "threshold_regime": signal.threshold_regime,
                        },
                    )
                except Exception as e:
                    logger.debug(f"Signal tracking skipped: {e}")
                return signal

            return None
        except InvalidSymbolError:
            logger.warning(f"Symbol {symbol} is invalid. Adding to ignore list.")
            self.invalid_symbols.add(symbol)
            return None

    def _partition_results(self, results) -> List[TradingSignal]:
        """تفکیک معنایی نتایج gather (قاعده ۳۰): سیگنال‌ها برمی‌گردند؛
        خطاها شمرده و لاگ می‌شوند و در last_errors می‌مانند تا caller
        «سیگنالی نیست» را از «تحلیل شکست خورد» تشخیص دهد."""
        signals = [res for res in results if isinstance(res, TradingSignal)]
        errors = [res for res in results if isinstance(res, Exception)]
        self.last_errors = len(errors)
        for err in errors:
            logger.error(f"Signal generation failed: {err}", exc_info=err)
        return signals

    def _passes_quality_gates(self, signal: TradingSignal) -> bool:
        """گیت‌های مرحله ۳ Pipeline (قاعده ۲۱) — فقط Ruleهای موجود."""
        # 3a. حداقل اطمینان هر تایم‌فریم
        thresholds = LONG_TERM_CONFIG.get("min_confidence_threshold", {})
        threshold = thresholds.get(signal.timeframe)
        if threshold is not None and signal.confidence_score < threshold:
            logger.debug(
                f"Gate confidence: {signal.confidence_score:.1f} < {threshold} "
                f"for {signal.symbol}-{signal.timeframe}"
            )
            return False

        # 3b. حداقل قدرت روند
        required = str(
            LONG_TERM_CONFIG.get("min_trend_strength", "MODERATE")
        ).upper()
        strength = signal.market_context.get("trend_strength")
        strength_name = getattr(strength, "value", strength)
        strength_name = str(strength_name).upper() if strength_name else "WEAK"
        if self._TREND_STRENGTH_RANK.get(
            strength_name, 0
        ) < self._TREND_STRENGTH_RANK.get(required, 1):
            logger.debug(
                f"Gate trend strength: {strength_name} < {required} "
                f"for {signal.symbol}-{signal.timeframe}"
            )
            return False

        # 3c. حداقل جهش حجم (از ratio حملی سیگنال، نه محاسبه مجدد)
        min_surge = LONG_TERM_CONFIG.get("min_volume_surge")
        ratio = (signal.volume_analysis or {}).get("volume_ratio")
        if min_surge is not None and ratio is not None:
            try:
                if float(ratio) < float(min_surge):
                    logger.debug(
                        f"Gate volume surge: {float(ratio):.2f} < {min_surge} "
                        f"for {signal.symbol}-{signal.timeframe}"
                    )
                    return False
            except (TypeError, ValueError):
                pass

        # 3d. اطمینان مدل (قاعده ۳۴): ml_confidence در گیت خوانده می‌شود.
        # مقیاس صفر تا یک است و فقط وقتی ML واقعاً اجرا شده (مقدار > 0) اعمال
        # می‌شود تا مسیر بک‌تست (include_ml=False → ml_confidence=0.0) رد نشود.
        # کف پیش‌فرض 0.0 یعنی بدون پیکربندی، هیچ سیگنالی از این گیت رد نمی‌شود
        # (رفتار موجود حفظ می‌شود؛ با تنظیم min_ml_confidence فعال می‌شود).
        min_ml_conf = LONG_TERM_CONFIG.get("min_ml_confidence", 0.0)
        ml_conf = getattr(signal, "ml_confidence", None)
        if ml_conf is not None and min_ml_conf:
            try:
                conf = float(ml_conf)
                if conf > 1.0:
                    conf /= 100.0
                if 0.0 < conf < float(min_ml_conf):
                    logger.debug(
                        f"Gate ml confidence: {conf:.3f} < {min_ml_conf} "
                        f"for {signal.symbol}-{signal.timeframe}"
                    )
                    return False
            except (TypeError, ValueError):
                pass

        return True

    async def run_analysis_for_all_symbols(self) -> List[TradingSignal]:
        # Reconciliation دوره‌ای pendingهای منقضی (قاعده ۳۱): مشابه
        # BacktestingEngine._flush_calibration اما برای مسیر Production.
        # خطای آن هرگز اجرای تحلیل را نمی‌شکند (قرارداد قاعده ۳۰).
        try:
            await self.reconcile_pending_signals()
        except Exception as e:
            logger.debug(f"Pending-signal reconciliation skipped: {e}")

        symbols = self.config_manager.get("symbols", [])
        focus_timeframes = LONG_TERM_CONFIG.get("focus_timeframes", ["1d", "1w", "1M"])
        all_timeframes = self.config_manager.get("timeframes", [])

        timeframes_to_use = [
            tf for tf in all_timeframes if tf in focus_timeframes
        ] or all_timeframes

        tasks = [
            self.analyze_symbol(s, tf) for s in symbols for tf in timeframes_to_use
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals = self._partition_results(results)

        if not signals:
            if self.last_errors:
                logger.warning(
                    f"No signals: {self.last_errors} analysis task(s) failed "
                    "in this cycle (distinct from 'no signal')."
                )
            else:
                logger.info("No signals generated in this analysis cycle")
            return []

        ranked_signals = SignalRanking.rank_signals(signals)

        # مرحله ۴ Pipeline (قاعده ۲۲): هر دو سقف موجود فعال‌اند —
        # اول سقف هر تایم‌فریم، بعد سقف کل خروجی (ترتیب رتبه حفظ می‌شود).
        per_tf_cap = self.config_manager.get("max_signals_per_timeframe", 1)
        try:
            per_tf_cap = max(1, int(per_tf_cap))
        except (TypeError, ValueError):
            per_tf_cap = 1
        seen_per_tf: dict = {}
        capped_signals = []
        for sig in ranked_signals:
            count = seen_per_tf.get(sig.timeframe, 0)
            if count < per_tf_cap:
                capped_signals.append(sig)
                seen_per_tf[sig.timeframe] = count + 1

        max_signals = LONG_TERM_CONFIG.get("max_signals_per_run", 3)
        final_signals = capped_signals[:max_signals]

        if final_signals:
            logger.info(
                f"Selected {len(final_signals)} top quality long-term signals from {len(signals)} candidates."
            )
            for i, sig in enumerate(final_signals, 1):
                logger.info(
                    f"  #{i}: {sig.symbol} {sig.timeframe} {sig.signal_type.value.upper()} "
                    f"(Confidence: {sig.confidence_score:.1f}%, R/R: {sig.risk_reward_ratio:.2f}, "
                    f"Rank Score: {SignalRanking.calculate_signal_score(sig):.2f})"
                )
        else:
            logger.info("No signals met the final quality criteria.")

        return final_signals

    async def run_quick_analysis(
        self, timeframes: Optional[List[str]] = None
    ) -> List[TradingSignal]:
        """تعریف واحد Quick Analysis (قاعده ۱۷): اسکن فقط تایم‌فریم‌های داده‌شده
        (پیش‌فرض ["1h"]) بدون رتبه‌بندی/محدودسازی نهایی. هم Telegram و هم
        TaskService از همین implementation استفاده می‌کنند.
        قاعده ۴۳: reconcile مستقل از مسیر Full است — اگر فقط اسکن دستی/سریع
        اجرا شود، pendingها باز هم resolve می‌شوند."""
        # Reconciliation دوره‌ای (قاعده ۴۳) — خطای آن اسکن را نمی‌شکند.
        try:
            await self.reconcile_pending_signals()
        except Exception as e:
            logger.debug(f"Pending-signal reconciliation skipped: {e}")

        symbols = self.config_manager.get("symbols", [])
        timeframes_to_run = timeframes or ["1h"]

        tasks = [
            self.analyze_symbol(symbol, tf)
            for symbol in symbols
            for tf in timeframes_to_run
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return self._partition_results(results)

    async def reconcile_pending_signals(self) -> int:
        """Reconciliation دوره‌ای سیگنال‌های زنده (قاعده ۳۱): pendingهای
        منقضی‌شده (طبق SIGNAL_EXPIRY_BY_TIMEFRAME) با قیمت واقعی مقایسه و
        resolve می‌شوند و حلقه کالیبراسیون (calibrator مدل‌ها +
        threshold_manager) از همین مسیر تغذیه می‌شود — مشابه
        BacktestingEngine._flush_calibration اما برای مسیر Production.
        قاعده ۴۲: قضاوت روی کندل‌های بین created_at و انقضا با لحاظ stop و
        target انجام می‌شود، نه فقط قیمت لحظه اجرا (قیمت لحظه‌ای فقط
        fallback است). تعداد resolveشده‌ها برمی‌گردد؛ خطای هر مورد طبق
        قاعده ۳۰ لاگ و رد می‌شود و تحلیل را نمی‌شکند."""
        expired = await self.signal_tracker.get_pending_expired()
        if not expired:
            return 0

        resolved_count = 0
        for item in expired:
            signal_id = item["signal_id"]
            details = item["details"]
            symbol = details.get("symbol")
            timeframe = details.get("timeframe")
            entry = details.get("entry")
            if not symbol or not timeframe or entry is None:
                logger.debug(f"Reconciliation skipped (missing fields): {signal_id}")
                continue
            try:
                created_at = SignalTracker._extract_created_at(signal_id, details)
                expiry_hours = SIGNAL_EXPIRY_BY_TIMEFRAME.get(timeframe)
                outcome = await self._decide_expired_outcome(
                    symbol, timeframe, details, created_at, expiry_hours
                )
                if outcome is None:
                    logger.debug(f"Reconciliation skipped (no price): {signal_id}")
                    continue
                success, resolved_price = outcome
                await self.signal_tracker.resolve(
                    signal_id,
                    success,
                    {
                        "resolved_price": resolved_price,
                        "resolution_source": "live_reconciliation",
                        "resolved_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                resolved_count += 1
                await self._record_live_calibration(symbol, timeframe, details, success)
            except Exception as e:
                logger.debug(f"Signal reconciliation skipped: {e}")

        if resolved_count:
            logger.info(f"Reconciled {resolved_count} expired pending signal(s).")
        return resolved_count

    async def _decide_expired_outcome(
        self,
        symbol: str,
        timeframe: str,
        details: Dict[str, Any],
        created_at: Optional[datetime],
        expiry_hours: Optional[float],
    ) -> Optional[Tuple[bool, float]]:
        """قضاوت نتیجه سیگنال منقضی (قاعده ۴۲): اول کندل‌های پنجره
        [created_at, created_at+expiry] بررسی می‌شوند —
        برخورد به stop یعنی شکست، برخورد به target یعنی موفقیت (اگر هر دو
        در یک کندل باشند، stop محافظه‌کارانه مقدم است). اگر stop/target ثبت
        نشده یا کندلی در دسترس نیست، fallback همان مقایسه قیمت لحظه با entry
        است. None یعنی قیمت در دسترس نیست (skip، نه Exception)."""
        try:
            entry = float(details.get("entry"))
        except (TypeError, ValueError):
            return None
        signal_type = str(details.get("signal_type", "")).lower()
        if signal_type not in ("buy", "sell"):
            return None

        try:
            stop = details.get("stop")
            stop = float(stop) if stop is not None else None
        except (TypeError, ValueError):
            stop = None
        try:
            target = details.get("target")
            target = float(target) if target is not None else None
        except (TypeError, ValueError):
            target = None

        if stop is not None and target is not None and created_at is not None:
            try:
                df = await self.market_data_provider.fetch_ohlcv_data(
                    symbol, timeframe, limit=500, bypass_cache=True
                )
            except Exception as e:
                logger.debug(f"Resolution candles fetch failed: {e}")
                df = None
            if df is not None and not df.empty:
                window = df[df.index >= created_at]
                if expiry_hours:
                    window = window[
                        window.index
                        <= created_at + timedelta(hours=expiry_hours)
                    ]
                for _, candle in window.iterrows():
                    try:
                        high = float(candle["high"])
                        low = float(candle["low"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if signal_type == "buy":
                        if low <= stop:
                            return False, stop
                        if high >= target:
                            return True, target
                    else:
                        if high >= stop:
                            return False, stop
                        if low <= target:
                            return True, target

        price = await self._get_reference_price(symbol, timeframe)
        if price is None:
            return None
        success = (
            price > entry
            if signal_type == "buy"
            else price < entry
        )
        return success, price

    async def _get_reference_price(
        self, symbol: str, timeframe: str
    ) -> Optional[float]:
        """قیمت مرجع برای reconciliation (قاعده ۳۱): آخرین close از Provider
        در لحظه اجرا. قاعده ۴۴: با bypass_cache=True تا قیمت کهنه از کش Redis
        (TTL تایم‌فریم) برنگردد. None یعنی قیمت در دسترس نیست (skip، نه
        Exception)."""
        try:
            df = await self.market_data_provider.fetch_ohlcv_data(
                symbol, timeframe, limit=2, bypass_cache=True
            )
            if df is None or df.empty:
                return None
            return float(df["close"].iloc[-1])
        except Exception as e:
            logger.debug(
                f"Reference price fetch failed for {symbol}-{timeframe}: {e}"
            )
            return None

    @staticmethod
    def _normalize_confidence_0_100(confidence: Any) -> float:
        """قرارداد مقیاس confidence (قاعده ۴۵): calibrator بازه ۰ تا ۱۰۰
        می‌خواهد (bin = int(conf*10/100)). confidence_score سیگنال ۰ تا ۱۰۰
        است و مستقیم مصرف می‌شود؛ اگر مقداری در بازه ۰ تا ۱ رسید (مثلاً
        ml_confidence که ۰ تا ۱ است)، به ۰ تا ۱۰۰ نگاشت می‌شود تا همه نمونه‌ها
        در bin صفر نیفتند."""
        try:
            conf = float(confidence or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if 0.0 < conf <= 1.0:
            conf *= 100.0
        return max(0.0, min(100.0, conf))

    async def _record_live_calibration(
        self, symbol: str, timeframe: str, details: Dict[str, Any], success: bool
    ) -> None:
        """تغذیه حلقه کالیبراسیون از نتیجه سیگنال زنده (قاعده ۳۱) — همان
        قرارداد BacktestingEngine._flush_calibration: confidence ترکیبی
        سیگنال به‌عنوان proxy مشترک lstm/xgboost (تفکیک per-model در
        قرارداد فعلی plumbing نشده — قاعده ۴۷، محدودیت مستند)، و آستانه
        تطبیقی فقط با هر سه جزء (رژیم کامل + آستانه > 0). قاعده ۴۵: ورودی
        calibrator با _normalize_confidence_0_100 نرمال می‌شود."""
        try:
            confidence = self._normalize_confidence_0_100(details.get("confidence", 0.0))
            if confidence > 0:
                for model_type in ("lstm", "xgboost"):
                    try:
                        await self.model_manager.record_signal_performance(
                            model_type, symbol, timeframe, confidence, success
                        )
                    except Exception as e:
                        logger.debug(f"Calibration flush skipped: {e}")
            # مسیر نوشتن آستانه تطبیقی — همان partition("|") بک‌تست.
            regime = str(details.get("threshold_regime") or "")
            vol_regime, _, hurst_range = regime.partition("|")
            threshold = float(details.get("threshold_used", 0.0) or 0.0)
            if vol_regime and hurst_range and threshold > 0:
                self.signal_generator.threshold_manager.record_performance(
                    vol_regime, hurst_range, threshold, success
                )
        except (TypeError, ValueError, AttributeError) as e:
            logger.debug(f"Live calibration feedback skipped: {e}")

    async def cleanup(self):
        """مالک ModelManager در سطح سرویس (قاعده ۲۵). Provider و ResourceManager
        متعلق به Application/Container‌اند و اینجا cleanup نمی‌شوند."""
        logger.info("Cleaning up TradingService resources.")
        if self.model_manager:
            await self.model_manager.shutdown()
