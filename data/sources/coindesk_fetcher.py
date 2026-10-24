import json
from typing import Any

import aiohttp
import pandas as pd
import redis

from common.cache import CacheCategory, CacheKeyBuilder
from common.exceptions import (
    APIRateLimitError,
    InvalidSymbolError,
    NetworkError,
    UpstreamUnavailableError,
)
from common.utils import RateLimiter, async_retry
from config.logger import logger
from data.sources.base_fetcher import BaseFetcher

coindesk_rate_limiter = RateLimiter(max_requests=20, time_window=60)

OHLCV_SUPPORTED_BASES = frozenset({"BTC", "ETH"})


class CoinDeskFetcher(BaseFetcher):
    def __init__(
        self,
        api_key: str,
        redis_client: redis.Redis | None = None,
        session: aiohttp.ClientSession | None = None,
        **kwargs,
    ):
        super().__init__(redis_client=redis_client, session=session, **kwargs)
        self.api_key = api_key
        self.base_url = "https://data-api.coindesk.com"
        self.source_name = "coindesk"

    @async_retry(
        attempts=3,
        delay=5,
        exceptions=(NetworkError, APIRateLimitError),
        ignore_exceptions=(InvalidSymbolError,),
    )
    async def _fetch(self, endpoint: str, params: dict | None = None):
        self._check_if_closed()
        headers = {"x-api-key": self.api_key}
        url = f"{self.base_url}/{endpoint}"
        await coindesk_rate_limiter.wait_if_needed(endpoint)

        async def _do_fetch():
            session = await self._get_session()
            try:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 403:
                        raise UpstreamUnavailableError(f"Upstream blocked access for {url}")
                    if response.status == 429:
                        raise APIRateLimitError("CoinDesk rate limit exceeded")
                    if response.status >= 400:
                        text = await response.text()
                        if "not found" in text.lower() or response.status == 404:
                            normalized = " ".join(text.split())[:200]
                            logger.warning(
                                f"CoinDesk not found for {url}: Status {response.status}, "
                                f"Body: {normalized}"
                            )
                            raise InvalidSymbolError(
                                f"Invalid symbol for CoinDesk: "
                                f"{params.get('symbol') if params else endpoint}"
                            )
                        raise NetworkError(f"HTTP Error {response.status} for {url}: {text}")
                    return await response.json()
            except (TimeoutError, aiohttp.ClientConnectorError) as exc:
                raise UpstreamUnavailableError(f"Upstream unavailable for {url}") from exc

        return await self.circuit_breaker.call(_do_fetch)

    def supports_ohlcv(self, symbol: str) -> bool:
        asset_id = symbol.upper().replace("/USDT", "").replace("/", "")
        return asset_id in OHLCV_SUPPORTED_BASES

    async def get_historical_ohlc(
        self, symbol: str, timeframe: str, limit: int
    ) -> pd.DataFrame | None:
        self._check_if_closed()
        try:
            timeframe_lower = timeframe.lower()
            original_symbol = symbol
            asset_id = symbol.upper().replace("/USDT", "").replace("/", "")

            if not self.supports_ohlcv(symbol):
                logger.debug(f"CoinDesk does not support symbol: {original_symbol}")
                raise InvalidSymbolError(f"CoinDesk does not support: {original_symbol}")

            if "d" in timeframe_lower or "w" in timeframe_lower or "m" in timeframe_lower:
                endpoint = "spot/v1/historical/days"
                aggregate = 1
            else:
                endpoint = "spot/v1/historical/hours"
                aggregate = 1

            params = {
                "market": "coinbase",
                "instrument": f"{asset_id}-USD",
                "limit": limit,
                "aggregate": aggregate,
                "fill": "true",
                "apply_mapping": "true",
                "response_format": "JSON",
            }

            data = await self._fetch(endpoint, params)

            if not data or "Data" not in data or not data["Data"]:
                return None

            ohlc_data = data["Data"]
            if not ohlc_data:
                return None

            df = pd.DataFrame(ohlc_data)
            df.rename(
                columns={
                    "TIMESTAMP": "timestamp",
                    "OPEN": "open",
                    "HIGH": "high",
                    "LOW": "low",
                    "CLOSE": "close",
                    "VOLUME": "volume",
                },
                inplace=True,
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
            df.set_index("timestamp", inplace=True)
            df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()

            return df.tail(limit)
        except InvalidSymbolError:
            logger.debug(f"Invalid symbol for CoinDesk OHLC: {symbol}")
            return None
        except Exception as e:
            logger.error(f"Error fetching historical OHLC from CoinDesk for {symbol}: {e}")
            return None

    async def get_news(self, symbols: list[str]) -> list[dict]:
        self._check_if_closed()
        try:
            all_news = []
            news_url = "https://api.coindesk.com/v1/news"
            params = {"slug": ",".join(s.lower().replace("-usdt", "") for s in symbols)}
            headers = {"X-CoinDesk-API-Key": self.api_key}

            session = await self._get_session()
            async with session.get(news_url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and "data" in data:
                        all_news.extend(data["data"])

            unique_news = list({item["id"]: item for item in all_news}.values())
            return unique_news
        except Exception as e:
            logger.error(f"Error fetching news from CoinDesk: {e}")
            return []

    async def get_bitcoin_price_index(self) -> dict[str, Any] | None:
        self._check_if_closed()
        cache_key = CacheKeyBuilder.indices_key(self.source_name, "bpi")
        cache_ttl = self.config_manager.get_cache_ttl("indices")

        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)

        try:
            session = await self._get_session()
            async with session.get("https://api.coindesk.com/v1/bpi/currentprice.json") as response:
                if response.status == 200:
                    data = await response.json()
                    if self.redis:
                        await self.redis.set(cache_key, json.dumps(data), ex=cache_ttl)
                    return data
            return None
        except Exception as e:
            logger.error(f"Error fetching Bitcoin Price Index from CoinDesk: {e}")
            return None

    async def get_latest_news(self, limit: int = 20) -> list[dict]:
        self._check_if_closed()
        cache_key = CacheKeyBuilder.build(
            CacheCategory.NEWS, self.source_name, ["latest", str(limit)]
        )
        cache_ttl = self.config_manager.get_cache_ttl("news")

        try:
            if self.redis:
                cached = await self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis GET failed for {cache_key}: {e}")

        try:
            news_url = "https://api.coindesk.com/v1/news/latest"
            params = {"limit": limit}
            headers = {"X-CoinDesk-API-Key": self.api_key}

            session = await self._get_session()
            async with session.get(news_url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    news_items = data.get("data", [])
                    if self.redis and news_items:
                        await self.redis.set(cache_key, json.dumps(news_items), ex=cache_ttl)
                    return news_items
            return []
        except Exception as e:
            logger.error(f"Error fetching latest news: {e}")
            return []
