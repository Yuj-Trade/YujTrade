from contextlib import asynccontextmanager

import aiohttp
import pytest
import yarl

from common.exceptions import InvalidSymbolError, NetworkError, UpstreamUnavailableError
from data.sources.base_fetcher import BaseFetcher
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitState


async def test_breaker_opens_after_repeated_upstream_unavailable():
    breaker = CircuitBreaker(failure_threshold=5, timeout=60)
    calls = 0

    async def _always_unavailable():
        nonlocal calls
        calls += 1
        raise UpstreamUnavailableError("upstream down")

    for _ in range(5):
        with pytest.raises(UpstreamUnavailableError):
            await breaker.call(_always_unavailable)

    assert breaker.state == CircuitState.OPEN

    with pytest.raises(CircuitBreakerError):
        await breaker.call(_always_unavailable)

    assert calls == 5


class _TimeoutSession:
    def __init__(self):
        self.calls = 0
        self.closed = False

    def get(self, *args, **kwargs):
        self.calls += 1

        @asynccontextmanager
        async def _ctx():
            raise TimeoutError("timed out")
            yield

        return _ctx()


async def test_timeout_becomes_upstream_unavailable_without_retry():
    session = _TimeoutSession()
    fetcher = BaseFetcher(session=session)

    with pytest.raises(UpstreamUnavailableError):
        await fetcher._fetch_json("https://example.test/endpoint")

    assert session.calls == 1


class _StatusSession:
    def __init__(self, status: int):
        self.status = status
        self.calls = 0
        self.closed = False

    def get(self, *args, **kwargs):
        self.calls += 1
        status = self.status

        @asynccontextmanager
        async def _ctx():
            class _Response:
                pass

            response = _Response()
            response.status = status

            async def _text():
                return "error"

            async def _json():
                return {}

            def _raise():
                raise aiohttp.ClientResponseError(
                    request_info=aiohttp.RequestInfo(
                        url=yarl.URL("https://example.test/endpoint"),
                        method="GET",
                        headers={},
                        real_url=yarl.URL("https://example.test/endpoint"),
                    ),
                    history=(),
                    status=status,
                    message="error",
                )

            response.text = _text
            response.json = _json
            response.raise_for_status = _raise
            yield response

        return _ctx()


@pytest.mark.parametrize("status", [400, 404])
async def test_client_errors_do_not_open_breaker(status):
    session = _StatusSession(status)
    fetcher = BaseFetcher(session=session)

    for _ in range(10):
        with pytest.raises((aiohttp.ClientResponseError, NetworkError, InvalidSymbolError)):
            await fetcher._fetch_json("https://example.test/endpoint")

    assert fetcher.circuit_breaker.state == CircuitState.CLOSED
