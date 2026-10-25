import asyncio
import time

import pytest

from common.rate_limit import (
    DEFAULT_LIMITS,
    RateLimitRegistry,
    configure_rate_limits,
    rate_limit_registry,
    reset_rate_limits,
)
from common.utils import RateLimiter
from config.settings import ConfigManager


@pytest.fixture(autouse=True)
def _reset():
    reset_rate_limits()
    yield
    reset_rate_limits()


async def test_configured_limits_are_applied():
    registry = RateLimitRegistry(
        {**DEFAULT_LIMITS, "coingecko": {"max_requests": 6, "time_window": 30}}
    )
    limiter = await registry.limiter("coingecko")

    assert limiter.max_requests == 6
    assert limiter.time_window == 30


async def test_unknown_provider_falls_back_to_default():
    registry = RateLimitRegistry(
        {"default": {"max_requests": 7, "time_window": 15, "scope": "endpoint"}}
    )
    limiter = await registry.limiter("unknown-provider")

    assert limiter.max_requests == 7
    assert limiter.time_window == 15


async def test_one_limiter_per_provider_is_shared():
    registry = RateLimitRegistry()

    first = await registry.limiter("coingecko")
    second = await registry.limiter("CoinGecko")

    assert first is second


async def test_provider_scope_shares_one_bucket_across_endpoints():
    limiter = RateLimiter(max_requests=2, time_window=0.3, scope="provider")

    await limiter.wait_if_needed("cpi")
    await limiter.wait_if_needed("gdp")

    started = time.monotonic()
    await limiter.wait_if_needed("unemployment")

    assert time.monotonic() - started >= 0.25


async def test_retry_after_cooldown_blocks_every_endpoint():
    limiter = RateLimiter(max_requests=100, time_window=60)
    await limiter.penalize(0.4)

    started = time.monotonic()
    await limiter.wait_if_needed("any-endpoint")

    assert time.monotonic() - started >= 0.35
    assert limiter.snapshot()["cooldown_count"] == 1


async def test_cooldown_expires_and_clears():
    limiter = RateLimiter(max_requests=100, time_window=60)
    await limiter.penalize(0.05)
    await limiter.wait_if_needed("endpoint")

    snapshot = limiter.snapshot()
    assert snapshot["cooldown_remaining"] == 0.0
    assert snapshot["cooldown_count"] == 1


async def test_snapshot_reports_counters():
    limiter = RateLimiter(max_requests=1, time_window=0.2, provider="coindesk")
    await limiter.wait_if_needed("endpoint")
    await asyncio.gather(limiter.wait_if_needed("endpoint"), limiter.wait_if_needed("endpoint"))

    snapshot = limiter.snapshot()
    assert snapshot["provider"] == "coindesk"
    assert snapshot["max_requests"] == 1
    assert snapshot["throttle_count"] >= 1
    assert snapshot["requests_in_window"] >= 1


def test_config_manager_exposes_rate_limits():
    limits = ConfigManager().get_rate_limits()

    assert "default" in limits
    assert limits["alphavantage"]["scope"] == "provider"


def test_configure_installs_the_registry():
    registry = configure_rate_limits({"default": {"max_requests": 3, "time_window": 5}})

    assert rate_limit_registry() is registry
