import asyncio
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, AsyncGenerator, Any, Generator

import aiohttp
import redis.asyncio as redis
import tensorflow as tf

from config.logger import logger
from config.settings import SecretsManager


class ResourceManager:
    """مالک انحصاری منابع خارجی (قاعده ۲۵): aiohttp session و Redis client.
    هیچ لایه دیگری آنها را نمی‌بندد (BaseFetcher.close عمداً session مشترک
    را دست نمی‌زند). سلسله‌مراتب cleanup:
    Application → Services/TradingService → Providers/Models → این‌جا."""
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._redis_client: Optional[redis.Redis] = None
        self._lock = asyncio.Lock()

    async def get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=60, connect=20, sock_read=30)
                self._session = aiohttp.ClientSession(timeout=timeout)
                logger.info("AIOHTTP session created.")
            return self._session

    async def get_redis_client(self) -> Optional[redis.Redis]:
        async with self._lock:
            if self._redis_client is None:
                host = SecretsManager.REDIS_HOST
                port = SecretsManager.REDIS_PORT
                password = SecretsManager.REDIS_PASSWORD

                if not all([host, port, password]):
                    logger.warning("Redis not fully configured. Caching will be disabled.")
                    return None

                redis_url = f"rediss://default:{password}@{host}:{port}"
                logger.debug(f"Connecting to Redis using URL: rediss://default:****@{host}:{port}")

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
                        ssl_cert_reqs=None
                    )

                    await asyncio.wait_for(self._redis_client.ping(), timeout=10.0)
                    logger.info("Connected to Redis successfully.")
                except asyncio.TimeoutError as e:
                    logger.warning(f"Redis connection timed out: {e}. Caching will be disabled.")
                    if self._redis_client:
                        try:
                            await self._redis_client.aclose()
                        except Exception as close_e:
                            logger.error(f"Error closing failed redis client: {close_e}")
                    self._redis_client = None
                except redis.ConnectionError as e:
                    logger.warning(f"Redis connection error: {e}. Caching will be disabled.")
                    if self._redis_client:
                        try:
                            await self._redis_client.aclose()
                        except Exception as close_e:
                            logger.error(f"Error closing failed redis client: {close_e}")
                    self._redis_client = None
                except redis.TimeoutError as e:
                    logger.warning(f"Redis timeout error: {e}. Caching will be disabled.")
                    if self._redis_client:
                        try:
                            await self._redis_client.aclose()
                        except Exception as close_e:
                            logger.error(f"Error closing failed redis client: {close_e}")
                    self._redis_client = None
                except Exception as e:
                    logger.error(f"Unexpected error connecting to Redis: {e}. Caching will be disabled.")
                    if self._redis_client:
                        try:
                            await self._redis_client.aclose()
                        except Exception as close_e:
                            logger.error(f"Error closing failed redis client: {close_e}")
                    self._redis_client = None

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

        logger.info("ResourceManager cleaned up successfully.")

    async def __aenter__(self):
        await self.get_session()
        await self.get_redis_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()


@contextmanager
def managed_tf_session() -> Generator[None, None, None]:
    try:
        yield
    finally:
        tf.keras.backend.clear_session()
        logger.debug("TensorFlow session cleared.")


@asynccontextmanager
async def managed_resource(resource: Any) -> AsyncGenerator[Any, None]:
    try:
        yield resource
    finally:
        if hasattr(resource, "close") and asyncio.iscoroutinefunction(resource.close):
            await resource.close()
        elif hasattr(resource, "shutdown") and asyncio.iscoroutinefunction(resource.shutdown):
            await resource.shutdown()
        elif hasattr(resource, "cleanup") and asyncio.iscoroutinefunction(resource.cleanup):
            await resource.cleanup()