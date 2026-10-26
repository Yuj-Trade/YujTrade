import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import aiohttp
import redis.asyncio as redis
import tensorflow as tf

from config.logger import logger
from config.settings import SecretsManager


class ResourceManager:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._redis_client: redis.Redis | None = None
        self._redis_unavailable = False
        self._lock = asyncio.Lock()

    async def get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=60, connect=20, sock_read=30)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logger.info("AIOHTTP session created.")
            return self._session

    @staticmethod
    def build_redis_url() -> str | None:
        if SecretsManager.REDIS_URL:
            return SecretsManager.REDIS_URL

        host = SecretsManager.REDIS_HOST
        port = SecretsManager.REDIS_PORT
        password = SecretsManager.REDIS_PASSWORD
        username = SecretsManager.REDIS_USERNAME or "default"

        if not all([host, port, password]):
            return None

        scheme = "rediss" if SecretsManager.REDIS_SSL else "redis"
        return f"{scheme}://{username}:{password}@{host}:{port}"

    @staticmethod
    def redact_redis_url(url: str) -> str:
        prefix, _, remainder = url.partition("://")
        credentials, _, host = remainder.rpartition("@")
        user = credentials.partition(":")[0]
        return f"{prefix}://{user}:****@{host}" if credentials else url

    async def _discard_redis_client(self) -> None:
        client, self._redis_client = self._redis_client, None
        if client is None:
            return
        try:
            await client.aclose()
        except Exception as close_e:
            logger.debug(f"Error closing failed redis client: {close_e}")

    async def get_redis_client(self) -> redis.Redis | None:
        async with self._lock:
            if self._redis_unavailable:
                return None

            if self._redis_client is None:
                redis_url = self.build_redis_url()
                if redis_url is None:
                    logger.warning("Redis not fully configured. Caching will be disabled.")
                    self._redis_unavailable = True
                    return None

                logger.debug(f"Connecting to Redis using URL: {self.redact_redis_url(redis_url)}")
                use_tls = redis_url.startswith("rediss://")
                tls_options = {"ssl_cert_reqs": None} if use_tls else {}

                try:
                    self._redis_client = redis.from_url(
                        redis_url,
                        decode_responses=True,
                        max_connections=50,
                        socket_connect_timeout=10,
                        socket_timeout=10,
                        socket_keepalive=True,
                        health_check_interval=30,
                        retry_on_timeout=True,
                        retry_on_error=[redis.ConnectionError, redis.TimeoutError],
                        **tls_options,
                    )

                    await asyncio.wait_for(self._redis_client.ping(), timeout=10.0)
                    logger.info(
                        f"Connected to Redis successfully ({'TLS' if use_tls else 'plain'})."
                    )
                except TimeoutError as e:
                    logger.warning(f"Redis connection timed out: {e}. Caching will be disabled.")
                    await self._discard_redis_client()
                except redis.ConnectionError as e:
                    logger.warning(f"Redis connection error: {e}. Caching will be disabled.")
                    await self._discard_redis_client()
                except redis.TimeoutError as e:
                    logger.warning(f"Redis timeout error: {e}. Caching will be disabled.")
                    await self._discard_redis_client()
                except Exception as e:
                    logger.error(
                        f"Unexpected error connecting to Redis: {e}. Caching will be disabled."
                    )
                    await self._discard_redis_client()

            if self._redis_client is None:
                self._redis_unavailable = True
            return self._redis_client

    async def cleanup(self):
        logger.info("Cleaning up ResourceManager...")
        async with self._lock:
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                    logger.info("AIOHTTP session closed.")
                except Exception as e:
                    logger.error(f"Error closing AIOHTTP session: {e}")

            if self._redis_client:
                try:
                    await self._redis_client.aclose()
                    logger.info("Redis client closed.")
                except Exception as e:
                    logger.error(f"Error closing Redis client: {e}")

            self._session = None
            self._redis_client = None
            self._redis_unavailable = False

        logger.info("ResourceManager cleaned up successfully.")

    async def __aenter__(self):
        await self.get_session()
        await self.get_redis_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()


@contextmanager
def managed_tf_session() -> Generator[None]:
    try:
        yield
    finally:
        tf.keras.backend.clear_session()
        logger.debug("TensorFlow session cleared.")


@asynccontextmanager
async def managed_resource(resource: Any) -> AsyncGenerator[Any]:
    try:
        yield resource
    finally:
        if hasattr(resource, "close") and asyncio.iscoroutinefunction(resource.close):
            await resource.close()
        elif hasattr(resource, "shutdown") and asyncio.iscoroutinefunction(resource.shutdown):
            await resource.shutdown()
        elif hasattr(resource, "cleanup") and asyncio.iscoroutinefunction(resource.cleanup):
            await resource.cleanup()
