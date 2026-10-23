import re

import aiohttp
import redis.asyncio as redis

from common.exceptions import (
    APIRateLimitError,
    InvalidSymbolError,
    NetworkError,
    ObjectClosedError,
    UpstreamUnavailableError,
)
from common.utils import RateLimiter, async_retry
from config.logger import logger
from config.settings import ConfigManager
from utils.circuit_breaker import CircuitBreaker

_TAG_PATTERN = re.compile(r"<[^>]*>")


class BaseFetcher:
    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        session: aiohttp.ClientSession | None = None,
        config_manager: ConfigManager | None = None,
    ):
        self.redis = redis_client
        self.session = session
        self.config_manager = config_manager or ConfigManager()
        self._is_closed = False
        self.circuit_breaker = CircuitBreaker()
        self.class_name = self.__class__.__name__

    def _check_if_closed(self):
        if self._is_closed:
            raise ObjectClosedError(f"{self.class_name} has been closed and cannot be used")

    async def _get_session(self) -> aiohttp.ClientSession:
        self._check_if_closed()
        if self.session is None or self.session.closed:
            raise RuntimeError(
                f"Session for {self.class_name} is not available. "
                "It should be provided by ResourceManager."
            )
        return self.session

    async def close(self):
        if self._is_closed:
            return
        self._is_closed = True
        logger.debug(f"Fetcher {self.class_name} instance closed (shared session not affected).")

    @async_retry(
        attempts=3,
        delay=5,
        exceptions=(NetworkError, APIRateLimitError),
        ignore_exceptions=(InvalidSymbolError,),
    )
    async def _fetch_json(
        self,
        url,
        params=None,
        headers=None,
        limiter: RateLimiter | None = None,
        endpoint_name: str = "default",
    ):
        self._check_if_closed()
        if limiter:
            await limiter.wait_if_needed(endpoint_name)

        async def _do_fetch():
            session = await self._get_session()
            try:
                response_cm = session.get(url, params=params, headers=headers)
                async with response_cm as response:
                    if response.status == 403:
                        raise UpstreamUnavailableError(f"Upstream blocked access for {url}")
                    if response.status == 429:
                        raise APIRateLimitError(f"Rate limit exceeded for {url}")
                    if response.status >= 400:
                        try:
                            error_text = await response.text()
                        except Exception as e:
                            logger.debug(f"Error body unreadable: {e}", exc_info=True)
                            error_text = "Could not read response body."

                        if "Invalid symbol" in error_text:
                            raise InvalidSymbolError(f"Invalid symbol for {url}")

                        normalized = " ".join(_TAG_PATTERN.sub(" ", error_text).split())[:200]
                        logger.error(
                            f"Error fetching from {url}: Status {response.status}, "
                            f"Body: {normalized}"
                        )
                        response.raise_for_status()
                    return await response.json()
            except (TimeoutError, aiohttp.ClientConnectorError) as exc:
                raise UpstreamUnavailableError(f"Upstream unavailable for {url}") from exc

        return await self.circuit_breaker.call(_do_fetch)
