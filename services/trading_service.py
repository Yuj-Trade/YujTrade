import asyncio
from typing import List, Optional, Set, Tuple

import pandas as pd

from config.settings import ConfigManager
from common.core import TradingSignal
from data.data_provider import MarketDataProvider
from config.logger import logger
from common.constants import LONG_TERM_CONFIG
from strategy.signal_generator import SignalGenerator
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from strategy.signal_ranking import SignalRanking
from strategy.signal_tracker import SignalTracker, make_signal_id
from modeling.model_manager import ModelManager, ModelDataProvider
from common.exceptions import InvalidSymbolError
from utils.resource_manager import ResourceManager


async def create_trading_stack(
    config_manager: Optional[ConfigManager] = None,
    resource_manager: Optional[ResourceManager] = None,
) -> Tuple[ConfigManager, ResourceManager, MarketDataProvider, "TradingService"]:
    """تنها Composition Root سیستم (شکاف ۱۸). MainApp، TaskServiceContainer و
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
                "model_auto_train_on_predict", True
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

        # مالک lifecycle رهگیری سیگنال در Pipeline اصلی (شکاف ۱۳).
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
        if symbol in self.invalid_symbols:
            logger.debug(f"Skipping analysis for invalid symbol: {symbol}")
            return None

        logger.info(f"Analyzing {symbol} on {timeframe} timeframe...")
        try:
            min_data_points = self.config_manager.get("min_data_points", {})
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

                logger.info(
                    f"Generated signal for {symbol} on {timeframe}: {signal.signal_type.value} with confidence {signal.confidence_score:.2f}"
                )
                # شروع lifecycle رهگیری: generated → pending (شکاف ۱۳).
                try:
                    self.signal_tracker.record(
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
        except KeyError as e:
            logger.error(
                f"KeyError encountered while analyzing {symbol} on {timeframe}: {e}",
                exc_info=True,
            )
            return None
        except ValueError as e:
            logger.error(
                f"ValueError encountered while analyzing {symbol} on {timeframe}: {e}"
            )
            return None
        except Exception as e:
            logger.error(f"Error analyzing {symbol} on {timeframe}: {e}", exc_info=True)
            return None

    async def run_analysis_for_all_symbols(self) -> List[TradingSignal]:
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

        signals = []
        for res in results:
            if isinstance(res, TradingSignal):
                signals.append(res)
            elif isinstance(res, Exception) and not isinstance(res, InvalidSymbolError):
                logger.error(f"Signal generation failed: {res}")

        if not signals:
            logger.info("No signals generated in this analysis cycle")
            return []

        ranked_signals = SignalRanking.rank_signals(signals)

        max_signals = LONG_TERM_CONFIG.get("max_signals_per_run", 3)
        final_signals = ranked_signals[:max_signals]

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
        """تعریف واحد Quick Analysis (شکاف ۱۷): اسکن فقط تایم‌فریم‌های داده‌شده
        (پیش‌فرض ["1h"]) بدون رتبه‌بندی/محدودسازی نهایی. هم Telegram و هم
        TaskService از همین implementation استفاده می‌کنند."""
        symbols = self.config_manager.get("symbols", [])
        timeframes_to_run = timeframes or ["1h"]

        tasks = [
            self.analyze_symbol(symbol, tf)
            for symbol in symbols
            for tf in timeframes_to_run
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return [res for res in results if isinstance(res, TradingSignal)]

    async def cleanup(self):
        logger.info("Cleaning up TradingService resources.")
        if self.model_manager:
            await self.model_manager.shutdown()
