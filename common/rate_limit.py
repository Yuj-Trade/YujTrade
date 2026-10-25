import asyncio
from typing import Any

from common.utils import RateLimiter
from config.logger import logger

DEFAULT_LIMITS: dict[str, dict[str, Any]] = {
    "default": {"max_requests": 60, "time_window": 60, "scope": "endpoint"},
    "binance": {"max_requests": 1200, "time_window": 60, "scope": "endpoint"},
    "coingecko": {"max_requests": 8, "time_window": 60, "scope": "endpoint"},
    "coindesk": {"max_requests": 20, "time_window": 60, "scope": "endpoint"},
    "alphavantage": {"max_requests": 5, "time_window": 60, "scope": "provider"},
    "cryptopanic": {"max_requests": 20, "time_window": 60, "scope": "endpoint"},
    "defillama": {"max_requests": 30, "time_window": 60, "scope": "endpoint"},
    "messari": {"max_requests": 20, "time_window": 60, "scope": "endpoint"},
    "alternativeme": {"max_requests": 20, "time_window": 60, "scope": "endpoint"},
}


class RateLimitRegistry:
    def __init__(self, limits: dict[str, dict[str, Any]] | None = None):
        self._limits = dict(limits) if limits else dict(DEFAULT_LIMITS)
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = asyncio.Lock()

    def _resolve(self, provider: str) -> dict[str, Any]:
        entry = self._limits.get(provider.lower())
        if entry is None:
            entry = self._limits.get("default", DEFAULT_LIMITS["default"])
        return entry

    async def limiter(self, provider: str) -> RateLimiter:
        key = provider.lower()
        async with self._lock:
            limiter = self._limiters.get(key)
            if limiter is None:
                entry = self._resolve(key)
                limiter = RateLimiter(
                    max_requests=int(entry.get("max_requests", 60)),
                    time_window=int(entry.get("time_window", 60)),
                    scope=str(entry.get("scope", "endpoint")),
                    provider=key,
                )
                self._limiters[key] = limiter
            return limiter

    async def wait(self, provider: str, endpoint: str) -> None:
        limiter = await self.limiter(provider)
        await limiter.wait_if_needed(endpoint)

    async def penalize(self, provider: str, seconds: float) -> None:
        limiter = await self.limiter(provider)
        await limiter.penalize(seconds)
        logger.warning(
            f"Rate limit cooldown for {provider.lower()}: pausing requests for {seconds:.1f}s"
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: limiter.snapshot() for name, limiter in self._limiters.items()}

    def register(self, provider: str, entry: dict[str, Any]) -> None:
        self._limits[provider.lower()] = dict(entry)
        self._limiters.pop(provider.lower(), None)


_registry: RateLimitRegistry | None = None


def configure_rate_limits(limits: dict[str, dict[str, Any]] | None) -> RateLimitRegistry:
    global _registry
    _registry = RateLimitRegistry(limits)
    return _registry


def rate_limit_registry() -> RateLimitRegistry:
    global _registry
    if _registry is None:
        _registry = RateLimitRegistry()
    return _registry


def reset_rate_limits() -> None:
    global _registry
    _registry = None
