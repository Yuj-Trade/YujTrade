import asyncio
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any

import aiohttp
import pandas as pd

from common.cache import CacheKeyBuilder
from common.constants import candle_duration
from common.core import (
    BinanceFuturesData,
    DerivativesAnalysis,
    FundamentalAnalysis,
    MacroEconomicData,
    OnChainAnalysis,
    OrderBook,
    TrendingData,
)
from common.exceptions import (
    DataError,
    InsufficientDataError,
    NetworkError,
    ObjectClosedError,
)
from common.utils import async_retry
from config.logger import logger
from config.settings import ConfigManager, SecretsManager
from data.data_validator import DataQualityChecker
from data.ohlcv_store import OhlcvStore
from data.sources.alphavantage_fetcher import AlphaVantageFetcher
from data.sources.alternativeme_fetcher import AlternativeMeFetcher
from data.sources.base_fetcher import report_fetch_failure
from data.sources.binance_fetcher import BinanceFetcher, klines_to_frame
from data.sources.coindesk_fetcher import CoinDeskFetcher
from data.sources.coingecko_fetcher import CoinGeckoFetcher
from data.sources.cryptopanic_fetcher import CryptoPanicFetcher
from data.sources.defillama_fetcher import DeFiLlamaFetcher
from data.sources.marketindices_fetcher import MarketIndicesFetcher
from data.sources.messari_fetcher import MessariFetcher
from data.sources.news_fetcher import NewsFetcher
from data.sources.yfinance_fetcher import YFinanceFetcher
from utils.resource_manager import ResourceManager

OHLCV_RANGE_PAGE_SIZE = 1000


class MarketDataProvider:
    def __init__(
        self,
        resource_manager: ResourceManager,
        config_manager: ConfigManager,
    ):
        self._is_closed = False
        self.resource_manager = resource_manager
        self.config_manager = config_manager
        self.redis: aiohttp.ClientSession | None = None
        self.session: aiohttp.ClientSession | None = None

        self.binance_fetcher: BinanceFetcher | None = None
        self.coindesk_fetcher: CoinDeskFetcher | None = None
        self.market_indices_fetcher: MarketIndicesFetcher | None = None
        self.coingecko_fetcher: CoinGeckoFetcher | None = None
        self.alphavantage_fetcher: AlphaVantageFetcher | None = None
        self.messari_fetcher: MessariFetcher | None = None
        self.news_fetcher: NewsFetcher | None = None
        self.defillama_fetcher: DeFiLlamaFetcher | None = None
        self.yfinance_fetcher: YFinanceFetcher | None = None

        self.fetchers: list[Any] = []

        self.data_quality_checker = DataQualityChecker()
        self.ohlcv_store: OhlcvStore | None = None

    async def initialize(self):
        if self.session is not None and not self.session.closed:
            return

        logger.info("Initializing MarketDataProvider...")

        try:
            self.session = await asyncio.wait_for(self.resource_manager.get_session(), timeout=10.0)
            logger.info("Session initialized successfully.")
        except TimeoutError:
            logger.error("Session initialization timed out.")
            raise

        try:
            self.redis = await asyncio.wait_for(
                self.resource_manager.get_redis_client(), timeout=10.0
            )
            if self.redis:
                logger.info("Redis client initialized successfully.")
            else:
                logger.warning("Redis client not available, continuing without cache.")
        except TimeoutError:
            logger.warning("Redis initialization timed out, continuing without cache.")
            self.redis = None
        except Exception as e:
            logger.warning(f"Redis initialization failed: {e}, continuing without cache.")
            self.redis = None

        if self.ohlcv_store is None and self.config_manager.get("ohlcv_store_enabled", True):
            self.ohlcv_store = OhlcvStore(
                path=self.config_manager.get("ohlcv_store_path", "runs/ohlcv.db"),
                max_rows_per_series=int(
                    self.config_manager.get("ohlcv_store_max_rows_per_series", 5000)
                ),
            )
            logger.info("OHLCV store initialized.")

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

        self.defillama_fetcher = DeFiLlamaFetcher(**common_args)
        self.yfinance_fetcher = YFinanceFetcher(**common_args)

        self.market_indices_fetcher = MarketIndicesFetcher(
            coingecko_fetcher=self.coingecko_fetcher,
            defillama_fetcher=self.defillama_fetcher,
            yfinance_fetcher=self.yfinance_fetcher,
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
                coindesk_fetcher=(
                    self.coindesk_fetcher
                    if self.config_manager.get("coindesk_news_enabled", False)
                    else None
                ),
                messari_fetcher=(
                    self.messari_fetcher
                    if self.config_manager.get("messari_enabled", False)
                    else None
                ),
                redis_client=self.redis,
                config_manager=self.config_manager,
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
        if self._is_closed:
            return
        self._is_closed = True
        close_tasks = [fetcher.close() for fetcher in self.fetchers if hasattr(fetcher, "close")]
        await asyncio.gather(*close_tasks, return_exceptions=True)
        if self.ohlcv_store is not None:
            await self.ohlcv_store.close()
        logger.info("MarketDataProvider and all associated fetchers cleaned up.")

    def _get_data_quality_score(self, df: pd.DataFrame, timeframe: str) -> float:
        if df is None or df.empty:
            return 0.0

        is_valid, _ = self.data_quality_checker.validate_data_quality(df, timeframe)
        if not is_valid:
            return 0.0

        score = 100.0

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
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
        bypass_cache: bool = False,
    ) -> pd.DataFrame | None:
        if self._is_closed:
            raise ObjectClosedError("MarketDataProvider is closed")

        if self.session is None or self.session.closed:
            await self.initialize()

        cache_key = CacheKeyBuilder.ohlcv_key("unified", symbol, timeframe)

        if not bypass_cache:
            cached = await self._read_cached_ohlcv(cache_key, symbol, timeframe, limit)
            if cached is not None:
                return cached

            stored = await self._read_stored_ohlcv(symbol, timeframe, limit)
            if stored is not None:
                return stored

        best_df = await self._fetch_ohlcv_from_sources(symbol, timeframe, limit)

        if not bypass_cache:
            await self._write_cached_ohlcv(cache_key, symbol, timeframe, best_df)
            await self._write_stored_ohlcv(symbol, timeframe, best_df)

        return best_df

    async def _read_cached_ohlcv(
        self, cache_key: str, symbol: str, timeframe: str, limit: int
    ) -> pd.DataFrame | None:
        if not self.redis:
            return None
        try:
            cached = await self.redis.get(cache_key)
        except Exception as e:
            logger.opt(exception=True).warning(f"Redis GET failed for {cache_key}: {e}")
            return None
        if not cached:
            return None

        try:
            df = pd.read_json(StringIO(cached), orient="split")
        except ValueError as e:
            logger.warning(f"Cached OHLCV unreadable for {cache_key}: {e}")
            return None

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)

        if len(df) < limit:
            logger.debug(f"Cached OHLCV for {symbol}-{timeframe} has {len(df)} < {limit} rows")
            return None

        try:
            df = self.data_quality_checker.repair_ohlcv(df, timeframe)
        except ValueError as exc:
            logger.warning(f"Cached OHLCV rejected: {exc}")
            return None

        is_valid, _ = self.data_quality_checker.validate_data_quality(df, timeframe)
        if not is_valid:
            logger.debug(f"Cached data for {symbol}-{timeframe} is invalid, refetching")
            return None
        return df

    async def _read_stored_ohlcv(
        self, symbol: str, timeframe: str, limit: int
    ) -> pd.DataFrame | None:
        if self.ohlcv_store is None:
            return None

        df = await self.ohlcv_store.read(symbol, timeframe, limit)
        if df is None or len(df) < limit:
            return None
        if not self._is_store_fresh(df, timeframe):
            logger.debug(f"Stored OHLCV for {symbol}-{timeframe} is stale, refetching")
            return None

        try:
            df = self.data_quality_checker.repair_ohlcv(df, timeframe)
        except ValueError as exc:
            logger.warning(f"Stored OHLCV rejected for {symbol}-{timeframe}: {exc}")
            return None

        is_valid, _ = self.data_quality_checker.validate_data_quality(df, timeframe)
        if not is_valid:
            return None

        logger.debug(f"Served {len(df)} candles for {symbol}-{timeframe} from the OHLCV store")
        return df

    def _is_store_fresh(self, df: pd.DataFrame, timeframe: str) -> bool:
        if df.empty or not isinstance(df.index, pd.DatetimeIndex):
            return False
        max_candles = float(self.config_manager.get("ohlcv_store_max_staleness_candles", 2))
        if max_candles <= 0:
            return True
        age = pd.Timestamp.now(tz="UTC") - df.index[-1]
        return age <= candle_duration(timeframe) * max_candles

    async def _write_cached_ohlcv(
        self, cache_key: str, symbol: str, timeframe: str, frame: pd.DataFrame
    ) -> None:
        if not self.redis:
            return
        try:
            payload = frame.reset_index(drop=True)
            payload.insert(0, "timestamp", frame.index.as_unit("ms").asi8)
            await self.redis.set(
                cache_key,
                payload.to_json(orient="split"),
                ex=self.config_manager.get_cache_ttl("ohlcv", timeframe),
            )
        except Exception as e:
            logger.opt(exception=True).warning(f"Redis SET failed for {cache_key}: {e}")

    async def _write_stored_ohlcv(self, symbol: str, timeframe: str, frame: pd.DataFrame) -> None:
        if self.ohlcv_store is None:
            return
        written = await self.ohlcv_store.write_many(symbol, timeframe, frame)
        if written:
            logger.debug(f"Stored {written} candles for {symbol}-{timeframe}")

    async def _fetch_ohlcv_from_sources(
        self, symbol: str, timeframe: str, limit: int
    ) -> pd.DataFrame:
        fetch_sources = [
            (
                (self.binance_fetcher.get_historical_ohlc, "binance")
                if self.binance_fetcher
                else None
            ),
            (
                (self.coindesk_fetcher.get_historical_ohlc, "coindesk")
                if self.coindesk_fetcher and self.coindesk_fetcher.supports_ohlcv(symbol)
                else None
            ),
        ]

        fetch_sources = [s for s in fetch_sources if s is not None]

        tasks = [fetch_func(symbol, timeframe, limit) for fetch_func, _ in fetch_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        best_df = None
        best_score = -1.0

        for i, res_df in enumerate(results):
            source_name = fetch_sources[i][1]
            if isinstance(res_df, Exception) or res_df is None or res_df.empty:
                logger.warning(f"Source {source_name} failed for {symbol}/{timeframe}: {res_df}")
                continue

            if isinstance(res_df.index, pd.DatetimeIndex):
                res_df.index = (
                    res_df.index.tz_convert("UTC")
                    if res_df.index.tz is not None
                    else res_df.index.tz_localize("UTC")
                )
            else:
                if "timestamp" in res_df.columns:
                    res_df["timestamp"] = pd.to_datetime(res_df["timestamp"], unit="ms", utc=True)
                    res_df.set_index("timestamp", inplace=True)
                else:
                    logger.warning(f"No timestamp column in data from {source_name}, skipping")
                    continue

            try:
                res_df = self.data_quality_checker.repair_ohlcv(res_df, timeframe)
            except ValueError as exc:
                logger.warning(f"Source {source_name} rejected after OHLCV repair check: {exc}")
                continue

            score = self._get_data_quality_score(res_df, timeframe)
            logger.debug(
                f"Data quality score for {symbol}/{timeframe} from {source_name}: {score:.2f}"
            )

            if score > best_score:
                best_score = score
                best_df = res_df

        if best_df is not None and not best_df.empty and best_score > 0:
            return best_df

        raise InsufficientDataError(
            f"Failed to fetch sufficient OHLCV for {symbol} on {timeframe} from all sources."
        )

    @async_retry(attempts=3, delay=5, exceptions=(NetworkError, DataError))
    async def fetch_ohlcv_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if self._is_closed:
            raise ObjectClosedError("MarketDataProvider is closed")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        if start_utc >= end_utc:
            raise ValueError("start must precede end")
        if self.session is None or self.session.closed:
            await self.initialize()
        if self.binance_fetcher is None:
            raise InsufficientDataError(f"No range-capable source for {symbol} on {timeframe}.")
        page_size = OHLCV_RANGE_PAGE_SIZE
        cursor = start_utc
        frames: list[pd.DataFrame] = []
        while cursor <= end_utc:
            rows = await self.binance_fetcher.get_kline_data(
                symbol,
                timeframe,
                start_time=int(cursor.timestamp() * 1000),
                end_time=int(end_utc.timestamp() * 1000),
                limit=page_size,
            )
            if not rows:
                break
            frames.append(klines_to_frame(rows))
            last_open = pd.to_datetime(rows[-1][0], unit="ms", utc=True)
            next_cursor = last_open.to_pydatetime() + timedelta(milliseconds=1)
            if next_cursor <= cursor or next_cursor > end_utc:
                break
            cursor = next_cursor
            if len(rows) < page_size:
                break
        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        combined = pd.concat(frames)
        combined = combined[~combined.index.duplicated(keep="first")].sort_index()
        in_window = combined[
            (combined.index >= pd.Timestamp(start_utc)) & (combined.index <= pd.Timestamp(end_utc))
        ]
        return in_window

    async def prewarm_ohlcv_store(
        self, symbols: list[str], timeframes: list[str], limit: int = 1000
    ) -> dict[str, int]:
        if self.ohlcv_store is None:
            return {}

        filled: dict[str, int] = {}
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    frame = await self.fetch_ohlcv_data(symbol, timeframe, limit)
                except Exception as exc:
                    logger.debug(f"Prewarm skipped {symbol}-{timeframe}: {exc}")
                    continue
                if frame is not None and not frame.empty:
                    filled[f"{symbol}-{timeframe}"] = len(frame)
        if filled:
            logger.info(f"Prewarmed the OHLCV store for {len(filled)} symbol/timeframe pairs")
        return filled

    async def get_derivatives_data(self, symbol: str) -> DerivativesAnalysis | None:
        if not self.binance_fetcher:
            return None
        bf = self.binance_fetcher
        try:
            tasks = {
                "open_interest": bf.get_open_interest(symbol),
                "funding_rate": bf.get_funding_rate(symbol),
                "long_short_ratio": bf.get_taker_long_short_ratio(symbol),
                "top_trader_accounts": bf.get_top_trader_long_short_ratio_accounts(symbol),
                "top_trader_positions": bf.get_top_trader_long_short_ratio_positions(symbol),
                "mark_price": bf.get_mark_price(symbol),
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
            report_fetch_failure(f"Error fetching derivatives data for {symbol}", e)
            return None

    async def get_fundamental_data(self, symbol: str) -> FundamentalAnalysis | None:
        if self.coingecko_fetcher:
            try:
                return await self.coingecko_fetcher.get_fundamental_data(symbol)
            except Exception as e:
                report_fetch_failure(f"Error fetching fundamental data for {symbol}", e)
        return None

    async def get_onchain_data(self, symbol: str) -> OnChainAnalysis | None:
        if self.messari_fetcher:
            try:
                return await self.messari_fetcher.get_on_chain_data(symbol)
            except Exception as e:
                report_fetch_failure(f"Error fetching on-chain data for {symbol}", e)
        return None

    async def get_order_book(self, symbol: str) -> OrderBook | None:
        if self.binance_fetcher:
            try:
                return await self.binance_fetcher.get_order_book_depth(symbol)
            except Exception as e:
                report_fetch_failure(f"Error fetching order book for {symbol}", e)
        return None

    async def get_macro_data(self) -> MacroEconomicData | None:
        if self.alphavantage_fetcher:
            try:
                data = await self.alphavantage_fetcher.get_macro_economic_data()
                if data:
                    return MacroEconomicData(
                        cpi=data.get("CPI"),
                        fed_rate=data.get("FED_RATE"),
                        treasury_yield_10y=data.get("TREASURY_YIELD"),
                        gdp=data.get("GDP"),
                        unemployment=data.get("UNEMPLOYMENT"),
                    )
            except Exception as e:
                report_fetch_failure("Error fetching macro data", e)
        return None

    async def get_trending_data(self) -> TrendingData | None:
        if self.coingecko_fetcher:
            try:
                trending = await self.coingecko_fetcher.get_trending_searches()
                if trending:
                    return TrendingData(coingecko_trending=trending)
            except Exception as e:
                report_fetch_failure("Error fetching trending data", e)
        return None

    async def get_news_sentiment(
        self, currencies: list[str] | None = None
    ) -> dict[str, Any] | None:
        if currencies is None:
            currencies = ["BTC", "ETH"]
        if self.news_fetcher:
            try:
                return await self.news_fetcher.fetch_sentiment_analysis(currencies)
            except Exception as e:
                report_fetch_failure("Error fetching news sentiment", e)
        return None

    async def get_market_indices(self) -> dict[str, Any] | None:
        if self.market_indices_fetcher:
            try:
                return await self.market_indices_fetcher.get_crypto_indices()
            except Exception as e:
                report_fetch_failure("Error fetching market indices", e)
        return None

    async def get_all_indices(self) -> dict[str, Any] | None:
        if self.market_indices_fetcher:
            try:
                return await self.market_indices_fetcher.get_all_indices()
            except Exception as e:
                report_fetch_failure("Error fetching all indices", e)
        return None
