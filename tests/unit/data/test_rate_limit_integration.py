from contextlib import asynccontextmanager

import pytest

from common.exceptions import APIRateLimitError
from common.rate_limit import configure_rate_limits, rate_limit_registry, reset_rate_limits
from data.sources.base_fetcher import BaseFetcher, retry_after_seconds


class _Response:
    def __init__(self, status: int, headers: dict[str, str]):
        self.status = status
        self.headers = headers

    async def text(self):
        return "rate limited"

    async def json(self):
        return {}


class _RateLimitedSession:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers
        self.closed = False

    def get(self, *args, **kwargs):
        headers = self.headers

        @asynccontextmanager
        async def _ctx():
            yield _Response(429, headers)

        return _ctx()


@pytest.fixture(autouse=True)
def _registry():
    configure_rate_limits(
        {"default": {"max_requests": 100, "time_window": 60, "scope": "endpoint"}}
    )
    yield
    reset_rate_limits()


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "30"}, 30.0),
        ({"Retry-After": "0.5"}, 1.0),
        ({}, 60.0),
        ({"Retry-After": "not-a-number"}, 60.0),
    ],
)
def test_retry_after_header_is_parsed(headers, expected):
    assert retry_after_seconds(_Response(429, headers)) == expected


async def test_a_429_parks_the_whole_provider():
    session = _RateLimitedSession({"Retry-After": "25"})
    fetcher = BaseFetcher(session=session)
    fetcher.source_name = "coindesk"

    with pytest.raises(APIRateLimitError):
        await BaseFetcher._fetch_json.__wrapped__(fetcher, "https://example.test/endpoint")

    snapshot = (await rate_limit_registry().limiter("coindesk")).snapshot()
    assert snapshot["cooldown_count"] == 1
    assert snapshot["cooldown_remaining"] > 20
