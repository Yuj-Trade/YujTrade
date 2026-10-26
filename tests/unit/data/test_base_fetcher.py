from contextlib import asynccontextmanager

import aiohttp
import pytest
import yarl

from common.exceptions import (
    APIRateLimitError,
    InvalidSymbolError,
    ObjectClosedError,
    UpstreamUnavailableError,
)
from common.rate_limit import reset_rate_limits
from data.sources.base_fetcher import BaseFetcher


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_rate_limits()
    yield
    reset_rate_limits()


class _Response:
    def __init__(self, status, payload=None, body="", headers=None):
        self.status = status
        self._payload = payload
        self._body = body
        self.headers = headers or {}

    async def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    async def text(self):
        return self._body

    def raise_for_status(self):
        if self.status < 400:
            return
        raise aiohttp.ClientResponseError(
            request_info=aiohttp.RequestInfo(
                url=yarl.URL("https://example.test/endpoint"),
                method="GET",
                headers={},
                real_url=yarl.URL("https://example.test/endpoint"),
            ),
            history=(),
            status=self.status,
            message="error",
        )


class _Session:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.closed = False
        self.urls = []

    def get(self, url, params=None, headers=None, **kwargs):
        self.urls.append(url)
        response, error = self.response, self.error

        @asynccontextmanager
        async def _ctx():
            if error is not None:
                raise error
            yield response

        return _ctx()


def _fetcher(response=None, error=None, **kwargs):
    session = _Session(response=response, error=error)
    fetcher = BaseFetcher(session=session, **kwargs)
    return fetcher, session


class TestFetchJson:
    async def test_success_returns_the_parsed_payload(self):
        fetcher, session = _fetcher(_Response(200, payload={"ok": True}))

        result = await fetcher._fetch_json("https://example.test/endpoint")

        assert result == {"ok": True}
        assert session.urls == ["https://example.test/endpoint"]

    async def test_forbidden_raises_upstream_unavailable(self):
        fetcher, _ = _fetcher(_Response(403))

        with pytest.raises(UpstreamUnavailableError, match="blocked access"):
            await fetcher._fetch_json("https://example.test/endpoint")

    async def test_rate_limit_raises_api_rate_limit(self):
        fetcher, _ = _fetcher(_Response(429, headers={"Retry-After": "30"}))

        with pytest.raises(APIRateLimitError):
            await BaseFetcher._fetch_json.__wrapped__(fetcher, "https://example.test/endpoint")

    async def test_invalid_symbol_body_raises_invalid_symbol(self):
        fetcher, _ = _fetcher(_Response(400, body='{"msg": "Invalid symbol."}'))

        with pytest.raises(InvalidSymbolError):
            await fetcher._fetch_json("https://example.test/endpoint")

    async def test_html_error_body_is_stripped_and_truncated(self, monkeypatch):
        body = "<html><body>" + ("x" * 500) + "</body></html>"
        fetcher, _ = _fetcher(_Response(500, body=body))

        captured: list[str] = []
        from data.sources import base_fetcher as module

        monkeypatch.setattr(module.logger, "error", lambda message: captured.append(message))

        with pytest.raises(aiohttp.ClientResponseError):
            await fetcher._fetch_json("https://example.test/endpoint")

        assert captured
        assert "<html>" not in captured[0]
        assert len(captured[0]) < 300

    async def test_timeout_becomes_upstream_unavailable(self):
        fetcher, _ = _fetcher(error=TimeoutError("slow"))

        with pytest.raises(UpstreamUnavailableError, match="unavailable"):
            await fetcher._fetch_json("https://example.test/endpoint")

    async def test_connector_error_becomes_upstream_unavailable(self):
        fetcher, _ = _fetcher(error=aiohttp.ClientConnectorError(None, OSError("dns")))

        with pytest.raises(UpstreamUnavailableError):
            await fetcher._fetch_json("https://example.test/endpoint")

    async def test_closed_fetcher_is_rejected(self):
        fetcher, _ = _fetcher(_Response(200, payload={}))
        await fetcher.close()

        with pytest.raises(ObjectClosedError):
            await fetcher._fetch_json("https://example.test/endpoint")

    async def test_missing_session_is_reported(self):
        fetcher = BaseFetcher(session=None)

        with pytest.raises(RuntimeError, match="not available"):
            await fetcher._fetch_json("https://example.test/endpoint")

    async def test_close_is_idempotent(self):
        fetcher, _ = _fetcher(_Response(200, payload={}))

        await fetcher.close()
        await fetcher.close()

        assert fetcher._is_closed is True

    async def test_custom_limiter_is_used(self):
        from common.utils import RateLimiter

        limiter = RateLimiter(max_requests=100, time_window=60)
        fetcher, _ = _fetcher(_Response(200, payload={}))

        result = await fetcher._fetch_json(
            "https://example.test/endpoint", limiter=limiter, endpoint_name="custom"
        )

        assert result == {}
        assert limiter.requests["custom"]

    async def test_default_limiter_is_resolved_from_the_registry(self):
        fetcher, _ = _fetcher(_Response(200, payload={}))
        fetcher.source_name = "coindesk"

        await fetcher._fetch_json("https://example.test/endpoint", endpoint_name="probe")

        from common.rate_limit import rate_limit_registry

        limiter = await rate_limit_registry().limiter("coindesk")
        assert limiter.requests["probe"]


class TestTransportErrorClassification:
    @pytest.mark.parametrize(
        "error",
        [
            aiohttp.ServerDisconnectedError(yarl.URL("https://example.test")),
            aiohttp.ClientOSError(104, "Connection reset by peer"),
            aiohttp.ClientPayloadError("truncated"),
            aiohttp.ServerTimeoutError("read timeout"),
            ConnectionResetError("reset"),
            ConnectionAbortedError("aborted"),
        ],
        ids=[
            "server-disconnected",
            "client-os",
            "payload",
            "server-timeout",
            "reset",
            "aborted",
        ],
    )
    async def test_transport_failures_become_upstream_unavailable(self, error):
        fetcher, _ = _fetcher(error=error)

        with pytest.raises(UpstreamUnavailableError):
            await fetcher._fetch_json("https://example.test/endpoint")

    async def test_a_transport_failure_counts_toward_the_breaker(self):
        fetcher, _ = _fetcher(error=aiohttp.ServerDisconnectedError())

        for _ in range(fetcher.circuit_breaker.failure_threshold):
            with pytest.raises(UpstreamUnavailableError):
                await fetcher._fetch_json("https://example.test/endpoint")

        assert fetcher.circuit_breaker.failure_count >= fetcher.circuit_breaker.failure_threshold

    async def test_an_application_error_is_not_reclassified(self):
        from common.exceptions import DataError

        fetcher, _ = _fetcher(error=DataError("bad payload"))

        with pytest.raises(DataError):
            await fetcher._fetch_json("https://example.test/endpoint")


class TestFailureReporting:
    def test_upstream_failures_stay_out_of_error(self):
        from config.logger import logger as configured_logger
        from data.sources.base_fetcher import report_fetch_failure

        messages: list[tuple[str, str]] = []
        handler_id = configured_logger.add(
            lambda m: messages.append((m.record["level"].name, m.record["message"])),
            format="{message}",
            level="DEBUG",
        )
        try:
            report_fetch_failure("Error fetching trending data", UpstreamUnavailableError("down"))
            report_fetch_failure("Error fetching trending data", RuntimeError("bug"))
        finally:
            configured_logger.remove(handler_id)

        levels = [level for level, _ in messages]
        assert levels == ["DEBUG", "ERROR"]

    def test_open_breaker_failures_stay_out_of_error(self):
        from config.logger import logger as configured_logger
        from data.sources.base_fetcher import report_fetch_failure
        from utils.circuit_breaker import CircuitBreakerError

        messages: list[tuple[str, str]] = []
        handler_id = configured_logger.add(
            lambda m: messages.append((m.record["level"].name, m.record["message"])),
            format="{message}",
            level="DEBUG",
        )
        try:
            report_fetch_failure("Error fetching open interest", CircuitBreakerError("open"))
        finally:
            configured_logger.remove(handler_id)

        assert messages[0][0] == "DEBUG"
