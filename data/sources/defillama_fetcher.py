import json

from common.cache import CacheCategory, CacheKeyBuilder
from common.utils import RateLimiter
from data.sources.base_fetcher import BaseFetcher

defillama_rate_limiter = RateLimiter(max_requests=30, time_window=60)


class DeFiLlamaFetcher(BaseFetcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = "https://api.llama.fi"
        self.source_name = "defillama"

    async def get_total_tvl_for_chains(self) -> list:
        url = f"{self.base_url}/v2/chains"
        data = await self._fetch_json(url, limiter=defillama_rate_limiter)
        return data if isinstance(data, list) else []

    async def get_protocol_chart(self, protocol: str) -> dict | None:
        cache_key = CacheKeyBuilder.build(
            CacheCategory.GENERIC, self.source_name, ["protocol_chart", protocol]
        )
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)

        url = f"{self.base_url}/protocol/{protocol}"
        data = await self._fetch_json(
            url, limiter=defillama_rate_limiter, endpoint_name=f"protocol_{protocol}"
        )

        if data and self.redis:
            await self.redis.set(
                cache_key,
                json.dumps(data),
                ex=self.config_manager.get_cache_ttl("defillama"),
            )
        return data

    async def get_defi_protocols(self) -> list[dict]:
        cache_key = CacheKeyBuilder.build(CacheCategory.GENERIC, self.source_name, ["protocols"])
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)

        url = f"{self.base_url}/protocols"
        data = await self._fetch_json(
            url, limiter=defillama_rate_limiter, endpoint_name="protocols"
        )

        if data and self.redis:
            await self.redis.set(
                cache_key,
                json.dumps(data),
                ex=self.config_manager.get_cache_ttl("defillama"),
            )
        return data if data else []

    async def get_chain_tvl(self, chain: str) -> dict | None:
        cache_key = CacheKeyBuilder.build(
            CacheCategory.METRICS, self.source_name, ["chain_tvl", chain]
        )
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)

        url = f"{self.base_url}/v2/historicalChainTvl/{chain}"
        data = await self._fetch_json(
            url, limiter=defillama_rate_limiter, endpoint_name=f"chain_tvl_{chain}"
        )

        if data and self.redis:
            await self.redis.set(
                cache_key,
                json.dumps(data),
                ex=self.config_manager.get_cache_ttl("defillama"),
            )
        return data

    async def get_stablecoins(self) -> dict | None:
        cache_key = CacheKeyBuilder.build(CacheCategory.GENERIC, self.source_name, ["stablecoins"])
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)

        url = f"{self.base_url}/stablecoins?includePrices=true"
        data = await self._fetch_json(
            url, limiter=defillama_rate_limiter, endpoint_name="stablecoins"
        )

        if data and self.redis:
            await self.redis.set(
                cache_key,
                json.dumps(data),
                ex=self.config_manager.get_cache_ttl("defillama"),
            )
        return data

    async def get_yields(self) -> list[dict]:
        cache_key = CacheKeyBuilder.build(CacheCategory.YIELD, self.source_name, ["all"])
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return json.loads(cached)

        url = f"{self.base_url}/pools"
        data = await self._fetch_json(url, limiter=defillama_rate_limiter, endpoint_name="yields")

        if data and "data" in data and self.redis:
            yield_data = data["data"]
            await self.redis.set(
                cache_key,
                json.dumps(yield_data),
                ex=self.config_manager.get_cache_ttl("defillama"),
            )
            return yield_data
        return []
