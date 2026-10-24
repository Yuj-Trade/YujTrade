import json
from typing import Any

import aiohttp
import redis

from common.cache import CacheCategory, CacheKeyBuilder
from common.core import OnChainAnalysis
from common.exceptions import (
    APIRateLimitError,
    DataError,
    InvalidSymbolError,
    NetworkError,
    UpstreamUnavailableError,
)
from common.utils import RateLimiter, async_retry
from config.logger import logger
from config.settings import ConfigManager
from data.sources.base_fetcher import BaseFetcher

messari_rate_limiter = RateLimiter(max_requests=20, time_window=60)


class MessariFetcher(BaseFetcher):
    def __init__(
        self,
        api_key: str,
        redis_client: redis.Redis | None = None,
        session: aiohttp.ClientSession | None = None,
        config_manager: ConfigManager | None = None,
    ):
        super().__init__(redis_client=redis_client, session=session, config_manager=config_manager)
        self.api_key = api_key
        self.base_url = "https://data.messari.io/api/v1"
        self.base_url_v2 = "https://data.messari.io/api/v2"
        self.source_name = "messari"

    def _enabled(self) -> bool:
        return bool(self.config_manager.get("messari_enabled", False))

    @async_retry(attempts=3, delay=5, exceptions=(NetworkError, APIRateLimitError))
    async def _fetch(self, endpoint: str, params: dict | None = None):
        self._check_if_closed()
        headers = {"x-messari-api-key": self.api_key}
        url = f"{self.base_url}/{endpoint}"
        await messari_rate_limiter.wait_if_needed(endpoint)

        async def _do_fetch():
            session = await self._get_session()
            try:
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 403:
                        raise UpstreamUnavailableError("Upstream blocked access for Messari")
                    if response.status == 429:
                        raise APIRateLimitError("Messari rate limit exceeded")
                    response.raise_for_status()
                    return await response.json()
            except (TimeoutError, aiohttp.ClientConnectorError) as exc:
                raise UpstreamUnavailableError(f"Upstream unavailable for {url}") from exc

        try:
            return await self.circuit_breaker.call(_do_fetch)
        except Exception as e:
            if isinstance(
                e, (NetworkError, APIRateLimitError, UpstreamUnavailableError, InvalidSymbolError)
            ):
                raise
            logger.opt(exception=True).error(f"Error in Messari _fetch for {url}: {e}")
            raise DataError(f"Failed to fetch data from Messari API: {url}") from e

    async def get_asset_metrics(self, symbol: str) -> dict[str, Any] | None:
        self._check_if_closed()
        if not self._enabled():
            return None
        cache_key = CacheKeyBuilder.build(
            CacheCategory.METRICS, self.source_name, ["asset"], symbol
        )
        try:
            if self.redis:
                cached = await self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis GET failed for {cache_key}: {e}")

        try:
            asset_id = symbol.split("/")[0].lower()
            data = await self._fetch(f"assets/{asset_id}/metrics")
            if data and "data" in data:
                metrics = data["data"]
                try:
                    if self.redis:
                        await self.redis.set(
                            cache_key,
                            json.dumps(metrics),
                            ex=self.config_manager.get_cache_ttl("onchain"),
                        )
                except Exception as e:
                    logger.warning(f"Redis SET failed for {cache_key}: {e}")
                return metrics
            return None
        except Exception as e:
            logger.error(f"Error fetching asset metrics from Messari for {symbol}: {e}")
            return None

    async def get_on_chain_data(self, symbol: str) -> OnChainAnalysis | None:
        self._check_if_closed()
        cache_key = CacheKeyBuilder.build(
            CacheCategory.METRICS, self.source_name, ["onchain"], symbol
        )
        try:
            if self.redis:
                cached = await self.redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return OnChainAnalysis(**data)
        except Exception as e:
            logger.warning(f"Redis GET failed for {cache_key}: {e}")

        try:
            metrics = await self.get_asset_metrics(symbol)
            if not metrics:
                return None

            analysis_data = {
                "mvrv": metrics.get("market_data", {}).get("mvrv_usd"),
                "sopr": metrics.get("on_chain_data", {}).get("sopr"),
                "active_addresses": metrics.get("on_chain_data", {}).get("active_addresses"),
                "realized_cap": metrics.get("marketcap", {}).get("realized_marketcap_usd"),
            }

            on_chain_analysis = OnChainAnalysis(**analysis_data)

            try:
                if self.redis:
                    await self.redis.set(
                        cache_key,
                        json.dumps(analysis_data),
                        ex=self.config_manager.get_cache_ttl("onchain"),
                    )
            except Exception as e:
                logger.warning(f"Redis SET failed for {cache_key}: {e}")

            return on_chain_analysis
        except Exception as e:
            logger.error(f"Error processing on-chain data from Messari for {symbol}: {e}")
            return None

    async def get_news(self, symbol: str) -> list[dict]:
        self._check_if_closed()
        if not self._enabled():
            return []
        cache_key = CacheKeyBuilder.build(CacheCategory.NEWS, self.source_name, ["news"], symbol)
        try:
            if self.redis:
                cached = await self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis GET failed for {cache_key}: {e}")

        try:
            asset_id = symbol.split("/")[0].lower()
            data = await self._fetch(f"assets/{asset_id}/news")
            if data and "data" in data:
                news_list = data["data"]
                if self.redis:
                    await self.redis.set(
                        cache_key,
                        json.dumps(news_list),
                        ex=self.config_manager.get_cache_ttl("news"),
                    )
                return news_list
            return []
        except Exception as e:
            logger.error(f"Error fetching news from Messari for {symbol}: {e}")
            return []
