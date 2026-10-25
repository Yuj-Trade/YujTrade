import asyncio
import time

from common.utils import RateLimiter


async def test_a_saturated_endpoint_does_not_delay_another_endpoint():
    limiter = RateLimiter(max_requests=1, time_window=0.6)
    await limiter.wait_if_needed("cpi")

    async def _wait_cpi():
        await limiter.wait_if_needed("cpi")

    sleeper = asyncio.create_task(_wait_cpi())
    await asyncio.sleep(0.05)

    started = time.monotonic()
    await limiter.wait_if_needed("gdp")
    elapsed = time.monotonic() - started

    assert elapsed < 0.2
    assert not sleeper.done()

    await sleeper


async def test_the_limit_is_enforced_per_endpoint():
    limiter = RateLimiter(max_requests=2, time_window=0.4)
    started = time.monotonic()

    await limiter.wait_if_needed("cpi")
    await limiter.wait_if_needed("cpi")
    await limiter.wait_if_needed("cpi")

    assert time.monotonic() - started >= 0.35


async def test_concurrent_callers_never_exceed_the_window_cap():
    limiter = RateLimiter(max_requests=3, time_window=0.3)
    completions: list[float] = []

    async def _call():
        await limiter.wait_if_needed("cpi")
        completions.append(time.monotonic())

    await asyncio.gather(*[_call() for _ in range(7)])

    completions.sort()
    for index in range(len(completions) - 3):
        window = completions[index + 3] - completions[index]
        assert window >= 0.25
