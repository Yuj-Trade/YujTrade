import time

import redis.asyncio as redis

from config.logger import logger


class ResilientRedis:
    def __init__(self, client: redis.Redis, report_interval: float = 300.0):
        self._client = client
        self._report_interval = report_interval
        self._last_report = 0.0
        self.suppressed_errors = 0

    @property
    def raw(self) -> redis.Redis:
        return self._client

    def _report(self, operation: str, exc: BaseException) -> None:
        now = time.monotonic()
        if now - self._last_report < self._report_interval:
            self.suppressed_errors += 1
            return
        self._last_report = now
        suppressed, self.suppressed_errors = self.suppressed_errors, 0
        suffix = f" ({suppressed} similar failures suppressed)" if suppressed else ""
        logger.warning(f"Redis {operation} failed: {exc}. Cache reads/writes degrade.{suffix}")

    async def get(self, key: str):
        try:
            return await self._client.get(key)
        except redis.RedisError as exc:
            self._report("GET", exc)
            return None

    async def set(self, key: str, value, ex: int | None = None, **kwargs):
        try:
            return await self._client.set(key, value, ex=ex, **kwargs)
        except redis.RedisError as exc:
            self._report("SET", exc)
            return None

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except redis.RedisError as exc:
            self._report("PING", exc)
            return False

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except redis.RedisError as exc:
            self._report("CLOSE", exc)
