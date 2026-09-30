import asyncio
from typing import Optional, List, Union, Dict, Any
from io import StringIO
import pandas as pd
import aiohttp

from data.sources.binance_fetcher import BinanceFetcher
from data.sources.coindesk_fetcher import CoinDeskFetcher
from data.sources.marketindices_fetcher import MarketIndicesFetcher
from data.sources.coingecko_fetcher import CoinGeckoFetcher
from data.sources.alphavantage_fetcher import AlphaVantageFetcher
from data.sources.messari_fetcher import MessariFetcher
from data.sources.news_fetcher import NewsFetcher
from data.sources.cryptopanic_fetcher import CryptoPanicFetcher
from data.sources.alternativeme_fetcher import AlternativeMeFetcher
from data.sources.defillama_fetcher import DeFiLlamaFetcher
from data.sources.yfinance_fetcher import YFinanceFetcher

from common.exceptions import (
    InsufficientDataError,
    NetworkError,
    DataError,
    ObjectClosedError,
)
from config.logger import logger
from common.utils import async_retry
from data.data_validator import DataQualityChecker
from common.cache import CacheKeyBuilder
from utils.resource_manager import ResourceManager
from config.settings import ConfigManager, SecretsManager
from common.core import (
    DerivativesAnalysis,
    BinanceFuturesData,
    FundamentalAnalysis,
    OnChainAnalysis,
    OrderBook,
    MacroEconomicData,
    TrendingData,
)


class MarketDataProvider:
    """قرارداد مالکیت Cache (شکاف ۲۴) — بدون double caching هم‌کلید:
    - Provider فقط کلید یکپارچه OHLCV (ohlcv_key با source="unified") را کش می‌کند.
    - هر Fetcher فقط کش دامنه خودش (derivatives/macro/indices/news/
      fundamental/trending/...) را با کلید نام‌منبع خودش مدیریت می‌کند.
    - متدهای get_*_data خروجی Fetcherها را دوباره کش نمی‌کنند؛ نتیجه
      تجمیعی MarketIndicesFetcher هم کش نمی‌شود (اجزا قبلاً کش شده‌اند).
    قرارداد خطا (شکاف ۳۰):
    - fetch_ohlcv_data در شکست یکپارچگی raise می‌کند (InsufficientDataError).
    - متدهای get_* enrichment اختیاری‌اند: None یعنی «در دسترس نیست»
      (تحلیل با degradation ادامه می‌یابد)، نه «شکست»."""
    def __init__(
        self,
        resource_manager: ResourceManager,
        config_manager: ConfigManager,
    ):
        self._is_closed = False
        self.resource_manager = resource_manager
        self.config_manager = config_manager
        self.redis: Optional[aiohttp.ClientSession] = None
        self.session: Optional[aiohttp.ClientSession] = None

        self.binance_fetcher: Optional[BinanceFetcher] = None
        self.coindesk_fetcher: Optional[CoinDeskFetcher] = None
        self.market_indices_fetcher: Optional[MarketIndicesFetcher] = None
        self.coingecko_fetcher: Optional[CoinGeckoFetcher] = None
        self.alphavantage_fetcher: Optional[AlphaVantageFetcher] = None
        self.messari_fetcher: Optional[MessariFetcher] = None
        self.news_fetcher: Optional[NewsFetcher] = None
        self.defillama_fetcher: Optional[DeFiLlamaFetcher] = None
        self.yfinance_fetcher: Optional[YFinanceFetcher] = None

        self.fetchers: List[Any] = []

        self.data_quality_checker = DataQualityChecker()

    async def initialize(self):
        if self.session is not None and not self.session.closed:
            return

        logger.info("Initializing MarketDataProvider...")
        
        try:
            self.session = await asyncio.wait_for(
                self.resource_manager.get_session(),
                timeout=10.0
            )
            logger.info("Session initialized successfully.")
        except asyncio.TimeoutError:
            logger.error("Session initialization timed out.")
            raise
        
        try:
            self.redis = await asyncio.wait_for(
                self.resource_manager.get_redis_client(),
                timeout=10.0
            )
            if self.redis:
                logger.info("Redis client initialized successfully.")
            else:
                logger.warning("Redis client not available, continuing without cache.")
        except asyncio.TimeoutError:
            logger.warning("Redis initialization timed out, continuing without cache.")
            self.redis = None
        except Exception as e:
            logger.warning(f"Redis initialization failed: {e}, continuing without cache.")
            self.redis = None

        common_args = {
            "redis_client": self.redis,
            "session": self.session,
            "config_manager": self.config_manager,
        }

        logger.info("Initializing data fetchers...")
        
        self.binance_fetcher = BinanceFetcher(**common_args)

        if SecretsManager.COINDESK_API_KEY:
            self.coindesk_fetcher = CoinDeskFetcher(
                api_key=SecretsManager.COINDESK_API_KEY, **common_args
            )

        self.coingecko_fetcher = CoinGeckoFetcher(
            api_key=SecretsManager.COINGECKO_KEY, **common_args
        )

        if SecretsManager.ALPHA_VANTAGE_KEY:
            self.alphavantage_fetcher = AlphaVantageFetcher(
                api_key=SecretsManager.ALPHA_VANTAGE_KEY, **common_args
            )

        if SecretsManager.MESSARI_API_KEY:
            self.messari_fetcher = MessariFetcher(
                api_key=SecretsManager.MESSARI_API_KEY, **common_args
            )

        # Source of Truth: DeFiLlama (on-chain TVL / DeFi) و YFinance
        # (شاخص‌های سنتی) همیشه ساخته می‌شوند چون کلید API لازم ندارند
        # و توسط MarketIndicesFetcher مصرف می‌شوند. ساخت صریح آن‌ها در
        # اینجا از نمونه‌سازی پنهان/تکراری داخل MarketIndicesFetcher
        # جلوگیری می‌کند و چرخه عمرشان زیر نظر MarketDataProvider است.
        self.defillama_fetcher = DeFiLlamaFetcher(**common_args)
        self.yfinance_fetcher = YFinanceFetcher(**common_args)

        self.market_indices_fetcher = MarketIndicesFetcher(
            coingecko_fetcher=self.coingecko_fetcher,
            defillama_fetcher=self.defillama_fetcher,
            yfinance_fetcher=self.yfinance_fetcher,
            alphavantage_fetcher=self.alphavantage_fetcher,
            **common_args,
        )

        if SecretsManager.CRYPTOPANIC_KEY:
            cryptopanic_fetcher = CryptoPanicFetcher(
                api_key=SecretsManager.CRYPTOPANIC_KEY, **common_args
            )
            alternativeme_fetcher = AlternativeMeFetcher(**common_args)

            self.news_fetcher = NewsFetcher(
                cryptopanic_fetcher=cryptopanic_fetcher,
                alternativeme_fetcher=alternativeme_fetcher,
                coindesk_fetcher=self.coindesk_fetcher,
                messari_fetcher=self.messari_fetcher,
                redis_client=self.redis,
            )

        self.fetchers = [
            f
            for f in [
                self.binance_fetcher,
                self.coindesk_fetcher,
                self.market_indices_fetcher,
                self.coingecko_fetcher,
                self.alphavantage_fetcher,
                self.messari_fetcher,
                self.news_fetcher,
                self.defillama_fetcher,
                self.yfinance_fetcher,
            ]
            if f is not None
        ]
        
        logger.info("MarketDataProvider initialization completed.")

    async def close(self):
        """مالک Fetcherها (شکاف ۲۵): همه Fetcherهای self.fetchers را می‌بندد
        (idempotent). session و Redis متعلق به ResourceManager‌اند و اینجا
        بسته نمی‌شوند."""
        if self._is_closed:
            return
        self._is_closed = True
        close_tasks = [
            fetcher.close() for fetcher in self.fetchers if hasattr(fetcher, "close")
        ]
        await asyncio.gather(*close_tasks, return_exceptions=True)
        logger.info("MarketDataProvider and all associated fetchers cleaned up.")

    def _get_data_quality_score(self, df: pd.DataFrame, timeframe: str) -> float:
        if df is None or df.empty:
            return 0.0

        is_valid, _ = self.data_quality_checker.validate_data_quality(df, timeframe)
        if not is_valid:
            return 0.0

        score = 100.0

        # قرارداد detect_data_gaps (عنصر اول) «has_gaps» است — همان
        #‌گونه که calculate_overall_quality_score آن را مصرف می‌کند. قبلاً
        # برعکس خوانده می‌شد: داده بدون گپ -۳۰ می‌گرفت و داده گپ‌دار
        # جریمه نمی‌شد (Regression P1 — تست‌های فاز ۸ آن را آشکار کردند).
        try:
            has_gaps, _ = self.data_quality_checker.detect_data_gaps(df)
            if has_gaps:
                score -= 30.0
        except ValueError:
            return 0.0

        if not self.data_quality_checker.check_sufficient_volume(df):
            score -= 20.0

        score -= df.isnull().sum().sum() * 0.1

        return score

    @async_retry(attempts=3, delay=5, exceptions=(NetworkError, DataError))
    async def fetch_ohlcv_data(
        self, symbol: str, timeframe: str, limit: int = 1000
    ) -> Optional[pd.DataFrame]:
        """نقش Provider در کیفیت داده (شکاف ۲۳): یکپارچگی Source/Data —
        فقط بهترین Source با امتیاز مثبت برگردانده می‌شود، وگرنه
        InsufficientDataError. آمادگی تحلیل (Signal) و نیازهای مدل (Model)
        در لایه‌های خودشان بررسی می‌شوند، نه اینجا."""
        if self._is_closed:
            raise ObjectClosedError("MarketDataProvider is closed")

        if self.session is None or self.session.closed:
            await self.initialize()

        cache_ttl = self.config_manager.get_cache_ttl("ohlcv", timeframe)

        cache_key = CacheKeyBuilder.ohlcv_key("unified", symbol, timeframe, limit)
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    df = pd.read_json(StringIO(cached), orient="split")
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(
                            df["timestamp"], unit="ms", utc=True
                        )
                        df.set_index("timestamp", inplace=True)
                    is_valid, _ = self.data_quality_checker.validate_data_quality(
                        df, timeframe
                    )
                    if not is_valid:
                        logger.debug(
                            f"Cached data for {symbol}-{timeframe} is invalid, refetching"
                        )
                    else:
                        return df
            except Exception as e:
                logger.warning(f"Redis GET failed for {cache_key}: {e}", exc_info=True)

        fetch_sources = [
            (
                (self.binance_fetcher.get_historical_ohlc, "binance")
                if self.binance_fetcher
                else None
            ),
            (
                (self.coindesk_fetcher.get_historical_ohlc, "coindesk")
                if self.coindesk_fetcher
                else None
            ),
        ]

        fetch_sources = [s for s in fetch_sources if s is not None]

        tasks = [
            fetch_func(symbol, timeframe, limit) for fetch_func, _ in fetch_sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        best_df = None
        best_score = -1.0

        for i, res_df in enumerate(results):
            source_name = fetch_sources[i][1]
            if isinstance(res_df, Exception) or res_df is None or res_df.empty:
                logger.warning(
                    f"Source {source_name} failed for {symbol}/{timeframe}: {res_df}"
                )
                continue

            if isinstance(res_df.index, pd.DatetimeIndex):
                res_df.index = (
                    res_df.index.tz_convert("UTC")
                    if res_df.index.tz is not None
                    else res_df.index.tz_localize("UTC")
                )
            else:
                if "timestamp" in res_df.columns:
                    res_df["timestamp"] = pd.to_datetime(
                        res_df["timestamp"], unit="ms", utc=True
                    )
                    res_df.set_index("timestamp", inplace=True)
                else:
                    logger.warning(
                        f"No timestamp column in data from {source_name}, skipping"
                    )
                    continue

            score = self._get_data_quality_score(res_df, timeframe)
            logger.debug(
                f"Data quality score for {symbol}/{timeframe} from {source_name}: {score:.2f}"
            )

            if score > best_score:
                best_score = score
                best_df = res_df

        if best_df is not None and not best_df.empty and best_score > 0:
            if self.redis:
                try:
                    df_to_cache = best_df.reset_index()
                    df_to_cache["timestamp"] = (
                        df_to_cache["timestamp"].astype(int) // 10**6
                    )
                    await self.redis.set(
                        cache_key, df_to_cache.to_json(orient="split"), ex=cache_ttl
                    )
                except Exception as e:
                    logger.warning(
                        f"Redis SET failed for {cache_key}: {e}", exc_info=True
                    )
            return best_df

        raise InsufficientDataError(
            f"Failed to fetch sufficient OHLCV for {symbol} on {timeframe} from all sources."
        )

    async def get_derivatives_data(self, symbol: str) -> Optional[DerivativesAnalysis]:
        if not self.binance_fetcher:
            return None

        try:
            tasks = {
                "open_interest": self.binance_fetcher.get_open_interest(symbol),
                "funding_rate": self.binance_fetcher.get_funding_rate(symbol),
                "long_short_ratio": self.binance_fetcher.get_taker_long_short_ratio(
                    symbol
                ),
                "top_trader_accounts": self.binance_fetcher.get_top_trader_long_short_ratio_accounts(
                    symbol
                ),
                "top_trader_positions": self.binance_fetcher.get_top_trader_long_short_ratio_positions(
                    symbol
                ),
                "mark_price": self.binance_fetcher.get_mark_price(symbol),
            }

            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            oi, fr, lsr, tta, ttp, mp = results

            binance_data = BinanceFuturesData(
                top_trader_long_short_ratio_accounts=tta
                if not isinstance(tta, Exception)
                else None,
                top_trader_long_short_ratio_positions=ttp
                if not isinstance(ttp, Exception)
                else None,
                mark_price=mp if not isinstance(mp, Exception) else None,
            )

            return DerivativesAnalysis(
                open_interest=oi if not isinstance(oi, Exception) else None,
                funding_rate=fr if not isinstance(fr, Exception) else None,
                taker_long_short_ratio=lsr if not isinstance(lsr, Exception) else None,
                binance_futures_data=binance_data,
            )
        except Exception as e:
            logger.error(f"Error fetching derivatives data for {symbol}: {e}")
            return None

    async def get_fundamental_data(self, symbol: str) -> Optional[FundamentalAnalysis]:
        if self.coingecko_fetcher:
            try:
                return await self.coingecko_fetcher.get_fundamental_data(symbol)
            except Exception as e:
                logger.error(f"Error fetching fundamental data for {symbol}: {e}")
        return None

    async def get_onchain_data(self, symbol: str) -> Optional[OnChainAnalysis]:
        """داده آن‌چین (MVRV/SOPR/active_addresses) از Messari موجود."""
        if self.messari_fetcher:
            try:
                return await self.messari_fetcher.get_on_chain_data(symbol)
            except Exception as e:
                logger.error(f"Error fetching on-chain data for {symbol}: {e}")
        return None

    async def get_order_book(self, symbol: str) -> Optional[OrderBook]:
        if self.binance_fetcher:
            try:
                return await self.binance_fetcher.get_order_book_depth(symbol)
            except Exception as e:
                logger.error(f"Error fetching order book for {symbol}: {e}")
        return None

    async def get_macro_data(self) -> Optional[MacroEconomicData]:
        if self.alphavantage_fetcher:
            try:
                data = await self.alphavantage_fetcher.get_comprehensive_macro_data()
                if data:
                    return MacroEconomicData(
                        cpi=data.get("CPI"),
                        fed_rate=data.get("FED_RATE"),
                        treasury_yield_10y=data.get("TREASURY_YIELD"),
                        gdp=data.get("GDP"),
                        unemployment=data.get("UNEMPLOYMENT"),
                    )
            except Exception as e:
                logger.error(f"Error fetching macro data: {e}")
        return None

    async def get_trending_data(self) -> Optional[TrendingData]:
        if self.coingecko_fetcher:
            try:
                trending = await self.coingecko_fetcher.get_trending_searches()
                if trending:
                    return TrendingData(coingecko_trending=trending)
            except Exception as e:
                logger.error(f"Error fetching trending data: {e}")
        return None

    async def get_news_sentiment(
        self, currencies: List[str] = ["BTC", "ETH"]
    ) -> Optional[Dict[str, Any]]:
        if self.news_fetcher:
            try:
                return await self.news_fetcher.fetch_sentiment_analysis(currencies)
            except Exception as e:
                logger.error(f"Error fetching news sentiment: {e}")
        return None

    async def get_market_indices(self) -> Optional[Dict[str, Any]]:
        """شاخص‌های کریپتو (TOTAL/BTC.D/DEFI_TVL/...) از مسیر موجود MarketIndicesFetcher."""
        if self.market_indices_fetcher:
            try:
                return await self.market_indices_fetcher.get_crypto_indices()
            except Exception as e:
                logger.error(f"Error fetching market indices: {e}")
        return None

    async def get_all_indices(self) -> Optional[Dict[str, Any]]:
        """ترکیب شاخص‌های کریپتو + سنتی + ماکرو از همان Aggregator موجود."""
        if self.market_indices_fetcher:
            try:
                return await self.market_indices_fetcher.get_all_indices()
            except Exception as e:
                logger.error(f"Error fetching all indices: {e}")
        return None
