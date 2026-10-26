from unittest.mock import AsyncMock

import redis.asyncio as redis

from config.logger import logger as configured_logger
from utils.resilient_redis import ResilientRedis


def _client(**methods):
    client = AsyncMock()
    for name, value in methods.items():
        setattr(client, name, value)
    return client


async def test_a_working_get_is_passed_through():
    client = _client(get=AsyncMock(return_value="value"))
    wrapper = ResilientRedis(client)

    assert await wrapper.get("key") == "value"
    client.get.assert_awaited_once_with("key")


async def test_a_working_set_is_passed_through():
    client = _client(set=AsyncMock(return_value=True))
    wrapper = ResilientRedis(client)

    assert await wrapper.set("key", "payload", ex=60) is True
    client.set.assert_awaited_once_with("key", "payload", ex=60)


async def test_a_failing_get_degrades_to_a_miss():
    client = _client(
        get=AsyncMock(side_effect=redis.ResponseError("max number of clients reached"))
    )
    wrapper = ResilientRedis(client)

    assert await wrapper.get("key") is None


async def test_a_failing_set_is_a_no_op():
    client = _client(
        set=AsyncMock(side_effect=redis.ResponseError("max number of clients reached"))
    )
    wrapper = ResilientRedis(client)

    assert await wrapper.set("key", "payload", ex=60) is None


async def test_a_connection_error_is_also_absorbed():
    client = _client(get=AsyncMock(side_effect=redis.ConnectionError("refused")))
    wrapper = ResilientRedis(client)

    assert await wrapper.get("key") is None


async def test_a_non_redis_error_still_propagates():
    client = _client(get=AsyncMock(side_effect=ValueError("bug")))
    wrapper = ResilientRedis(client)

    try:
        await wrapper.get("key")
    except ValueError:
        return
    raise AssertionError("expected ValueError to propagate")


async def test_failures_are_reported_once_per_interval():
    client = _client(get=AsyncMock(side_effect=redis.ResponseError("limit")))
    wrapper = ResilientRedis(client, report_interval=300.0)
    warnings: list[str] = []
    handler_id = configured_logger.add(
        lambda m: warnings.append(m.record["message"]), format="{message}", level="WARNING"
    )
    try:
        for _ in range(5):
            await wrapper.get("key")
    finally:
        configured_logger.remove(handler_id)

    assert len(warnings) == 1
    assert "Redis GET failed" in warnings[0]
    assert wrapper.suppressed_errors == 4


async def test_a_later_failure_reports_the_suppressed_count():
    import asyncio

    client = _client(get=AsyncMock(side_effect=redis.ResponseError("limit")))
    wrapper = ResilientRedis(client, report_interval=0.05)
    warnings: list[str] = []
    handler_id = configured_logger.add(
        lambda m: warnings.append(m.record["message"]), format="{message}", level="WARNING"
    )
    try:
        await wrapper.get("key")
        await wrapper.get("key")
        await asyncio.sleep(0.06)
        await wrapper.get("key")
    finally:
        configured_logger.remove(handler_id)

    assert len(warnings) == 2
    assert "suppressed" not in warnings[0]
    assert "1 similar failures suppressed" in warnings[1]


async def test_ping_reports_unavailability():
    client = _client(ping=AsyncMock(side_effect=redis.ConnectionError("down")))
    wrapper = ResilientRedis(client)

    assert await wrapper.ping() is False


async def test_close_absorbs_a_failure():
    client = _client(aclose=AsyncMock(side_effect=redis.ConnectionError("down")))
    wrapper = ResilientRedis(client)

    await wrapper.aclose()


async def test_the_raw_client_is_reachable():
    client = _client()
    wrapper = ResilientRedis(client)

    assert wrapper.raw is client
