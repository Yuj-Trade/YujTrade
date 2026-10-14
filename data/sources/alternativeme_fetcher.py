import json
from typing import Any

from common.cache import CacheCategory, CacheKeyBuilder
from common.utils import RateLimiter
from data.sources.base_fetcher import BaseFetcher

alternative_me_rate_limiter = RateLimiter(max_requests=20, time_window=60)


class AlternativeMeFetcher(BaseFetcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.source_name = "alternative.me"

    async def fetch_fear_greed(self, limit: int = 1) -> list[dict[str, Any]]:
        cache_key = CacheKeyBuilder.build(CacheCategory.FEAR_GREED, self.source_name, [str(limit)])
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)

        url = f"https://api.alternative.me/fng/?limit={limit}"
        data = await self._fetch_json(url, limiter=alternative_me_rate_limiter, endpoint_name="fng")

        results = data.get("data", [])
        if results and self.redis:
            await self.redis.set(
                cache_key,
                json.dumps(results),
                ex=self.config_manager.get_cache_ttl("fear_greed"),
            )
        return results
