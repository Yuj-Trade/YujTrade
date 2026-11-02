from unittest.mock import AsyncMock

import redis.asyncio as redis

import utils.resilient_redis as resilient_redis
from config.logger import logger as configured_logger
from utils.resilient_redis import ResilientRedis


def _client(**methods):
    client = AsyncMock()
    for name, value in methods.items():
        setattr(client, name, value)
    return client


async def test_the_first_failure_is_reported_on_a_low_uptime_host(monkeypatch):
    monkeypatch.setattr(resilient_redis.time, "monotonic", lambda: 10.0)
    client = _client(get=AsyncMock(side_effect=redis.ConnectionError("down")))
    wrapper = ResilientRedis(client, report_interval=300.0)
    warnings: list[str] = []
    handler_id = configured_logger.add(
        lambda m: warnings.append(m.record["message"]), format="{message}", level="WARNING"
    )
    try:
        await wrapper.get("key")
    finally:
        configured_logger.remove(handler_id)

    assert len(warnings) == 1
    assert "Redis GET failed" in warnings[0]
    assert wrapper.suppressed_errors == 0
