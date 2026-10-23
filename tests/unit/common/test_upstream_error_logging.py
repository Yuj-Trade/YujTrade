from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
import yarl
from loguru import logger

from data.sources.base_fetcher import BaseFetcher


class _FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    async def text(self):
        return self._body

    async def json(self):
        return {}

    def raise_for_status(self):
        raise aiohttp.ClientResponseError(
            request_info=aiohttp.RequestInfo(
                url=yarl.URL("https://example.test/endpoint"),
                method="GET",
                headers={},
                real_url=yarl.URL("https://example.test/endpoint"),
            ),
            history=(),
            status=self.status,
            message="Upstream error",
        )


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.closed = False

    def get(self, *args, **kwargs):
        response = self._response

        @asynccontextmanager
        async def _ctx():
            yield response

        return _ctx()


def _build_fetcher(response: _FakeResponse) -> BaseFetcher:
    fetcher = BaseFetcher(session=_FakeSession(response))

    async def _passthrough(fn):
        return await fn()

    fetcher.circuit_breaker = MagicMock()
    fetcher.circuit_breaker.call = AsyncMock(side_effect=_passthrough)
    return fetcher


async def test_upstream_error_body_is_truncated_in_log_output():
    huge_body = "<html><body>" + ("x" * 5000) + "</body></html>"
    fetcher = _build_fetcher(_FakeResponse(500, huge_body))

    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        with pytest.raises(aiohttp.ClientResponseError):
            await fetcher._fetch_json("https://example.test/endpoint")
    finally:
        logger.remove(handler_id)

    captured = "\n".join(messages)
    assert captured, "expected an error log line"
    assert "<html" not in captured
    assert len(captured) < 400
