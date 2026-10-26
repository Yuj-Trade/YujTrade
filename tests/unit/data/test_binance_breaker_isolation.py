from contextlib import asynccontextmanager

import pytest

from common.exceptions import DataError, UpstreamUnavailableError
from config.logger import logger as configured_logger
from data.sources.base_fetcher import report_fetch_failure
from data.sources.binance_fetcher import BinanceFetcher
from utils.circuit_breaker import CircuitBreakerError, CircuitState


class _HostAwareSession:
    def __init__(self, failing_host: str):
        self.failing_host = failing_host
        self.calls: list[str] = []
        self.closed = False

    def get(self, url, params=None, headers=None, **kwargs):
        self.calls.append(url)
        failing = self.failing_host in url

        @asynccontextmanager
        async def _ctx():
            if failing:
                raise TimeoutError("timed out")

            class _Response:
                status = 200

                async def json(self):
                    return {"ok": True}

                async def text(self):
                    return ""

            yield _Response()

        return _ctx()


async def test_futures_timeouts_do_not_block_spot_requests():
    session = _HostAwareSession("fapi.binance.com")
    fetcher = BinanceFetcher(session=session)

    for _ in range(5):
        with pytest.raises(UpstreamUnavailableError):
            await fetcher._fetch(fetcher.fapi_url, "openInterest", {"symbol": "BTCUSDT"})

    assert fetcher.futures_circuit_breaker.state == CircuitState.OPEN
    assert fetcher.circuit_breaker.state == CircuitState.CLOSED

    result = await fetcher._fetch(fetcher.base_url, "klines", {"symbol": "BTCUSDT"})

    assert result == {"ok": True}
    assert fetcher.circuit_breaker.state == CircuitState.CLOSED


def _capture(level: str):
    messages: list[tuple[str, str]] = []

    def sink(message):
        messages.append((message.record["level"].name, message.record["message"]))

    handler_id = configured_logger.add(sink, format="{message}", level=level)
    return messages, handler_id


def test_upstream_unavailable_failures_do_not_log_at_error_level():
    messages, handler_id = _capture("DEBUG")
    try:
        report_fetch_failure(
            "Error fetching open interest for BTC/USDT", UpstreamUnavailableError("down")
        )
        report_fetch_failure(
            "Error fetching open interest for ETH/USDT", CircuitBreakerError("open")
        )
        report_fetch_failure("Error fetching open interest for SOL/USDT", DataError("broken"))
    finally:
        configured_logger.remove(handler_id)

    errors = [m for level, m in messages if level == "ERROR"]
    assert len(errors) == 1
    assert "SOL/USDT" in errors[0]
    assert len([level for level, _ in messages if level == "DEBUG"]) == 2
