import pytest
import redis.asyncio as redis

from config.logger import logger as configured_logger
from config.settings import SecretsManager
from utils.resource_manager import ResourceManager


class _FailingClient:
    def __init__(self):
        self.pings = 0
        self.closed = False

    async def ping(self):
        self.pings += 1
        raise redis.ConnectionError("Error 11001 connecting to redis.example:6379")

    async def aclose(self):
        self.closed = True


@pytest.fixture
def failing_redis(monkeypatch):
    client = _FailingClient()
    monkeypatch.setattr(SecretsManager, "REDIS_HOST", "redis.example")
    monkeypatch.setattr(SecretsManager, "REDIS_PORT", "6379")
    monkeypatch.setattr(SecretsManager, "REDIS_PASSWORD", "secret")
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: client)
    return client


async def test_failed_redis_connection_is_not_retried(failing_redis):
    manager = ResourceManager()

    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = configured_logger.add(sink, format="{message}", level="WARNING")
    try:
        assert await manager.get_redis_client() is None
        assert await manager.get_redis_client() is None
        assert await manager.get_redis_client() is None
    finally:
        configured_logger.remove(handler_id)

    assert failing_redis.pings == 1
    assert len([m for m in messages if "Redis connection error" in m]) == 1


async def test_cleanup_resets_the_unavailable_flag(failing_redis):
    manager = ResourceManager()
    assert await manager.get_redis_client() is None
    assert manager._redis_unavailable is True

    await manager.cleanup()
    assert manager._redis_unavailable is False
