from contextlib import asynccontextmanager

import pytest

from common.exceptions import UpstreamUnavailableError
from data.sources.binance_fetcher import BinanceFetcher
from utils.circuit_breaker import CircuitState


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
