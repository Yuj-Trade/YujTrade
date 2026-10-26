import asyncio
import json
from typing import Any

from common.cache import CacheKeyBuilder
from config.logger import logger
from data.sources.base_fetcher import BaseFetcher

MACRO_SERIES: dict[str, dict[str, str]] = {
    "CPI": {"function": "CPI", "interval": "monthly"},
    "FED_RATE": {"function": "FEDERAL_FUNDS_RATE", "interval": "monthly"},
    "GDP": {"function": "REAL_GDP", "interval": "quarterly"},
    "UNEMPLOYMENT": {"function": "UNEMPLOYMENT"},
    "TREASURY_YIELD": {
        "function": "TREASURY_YIELD",
        "interval": "monthly",
        "maturity": "10year",
    },
}


class AlphaVantageFetcher(BaseFetcher):
    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"
        self.source_name = "alphavantage"
        self._macro_lock = asyncio.Lock()
        self._macro_inflight: asyncio.Task | None = None

    @staticmethod
    def _latest_value(payload: Any) -> float | None:
        if not isinstance(payload, dict):
            return None
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        first = rows[0]
        if not isinstance(first, dict):
            return None
        try:
            return float(first["value"])
        except (KeyError, TypeError, ValueError):
            return None

    async def _read_macro_cache(self, cache_key: str) -> dict[str, Any] | None:
        if not self.redis:
            return None
        try:
            cached = await self.redis.get(cache_key)
        except Exception as e:
            logger.warning(f"Redis GET failed for {cache_key}: {e}")
            return None
        if not cached:
            return None
        try:
            payload = json.loads(cached)
        except (TypeError, ValueError) as e:
            logger.warning(f"Discarding unreadable macro cache entry {cache_key}: {e}")
            return None
        return payload if isinstance(payload, dict) else None

    async def _fetch_macro_series(self, cache_key: str, cache_ttl: int) -> dict[str, Any]:
        requests = {
            name: self._fetch_json(
                self.base_url,
                params={**params, "apikey": self.api_key},
                endpoint_name=name.lower(),
            )
            for name, params in MACRO_SERIES.items()
        }
        results = await asyncio.gather(*requests.values(), return_exceptions=True)

        macro_data: dict[str, Any] = {}
        for name, result in zip(requests.keys(), results, strict=False):
            if isinstance(result, Exception):
                continue
            value = self._latest_value(result)
            if value is not None:
                macro_data[name] = value

        if self.redis and macro_data:
            try:
                await self.redis.set(cache_key, json.dumps(macro_data), ex=cache_ttl)
            except Exception as e:
                logger.warning(f"Redis SET failed for {cache_key}: {e}")

        return macro_data

    async def get_macro_economic_data(self) -> dict[str, Any]:
        self._check_if_closed()
        cache_key = CacheKeyBuilder.macro_key(self.source_name, "economic")
        cache_ttl = self.config_manager.get_cache_ttl("macro")

        cached = await self._read_macro_cache(cache_key)
        if cached is not None:
            return cached

        if not self.api_key:
            return {}

        async with self._macro_lock:
            inflight = self._macro_inflight
            if inflight is None or inflight.done():
                cached = await self._read_macro_cache(cache_key)
                if cached is not None:
                    return cached
                inflight = asyncio.ensure_future(self._fetch_macro_series(cache_key, cache_ttl))
                self._macro_inflight = inflight

        return await asyncio.shield(inflight)
