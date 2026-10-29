import os

import pytest

from trading.exchanges.credentials import load_exchange_credentials
from trading.exchanges.factory import build_gateway
from trading.exchanges.registry import get_spec

SANDBOX_ENABLED = os.environ.get("YUJTRADE_SANDBOX_TESTS") == "1"

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(not SANDBOX_ENABLED, reason="YUJTRADE_SANDBOX_TESTS is not 1"),
]


def _credentials_or_skip(exchange_id: str):
    spec = get_spec(exchange_id)
    credentials = load_exchange_credentials(spec, sandbox=True)
    if credentials is None:
        pytest.skip(f"no sandbox credentials for {exchange_id}")
    return spec, credentials


@pytest.mark.asyncio
async def test_binance_sandbox_markets_and_ticker():
    spec, credentials = _credentials_or_skip("binance")
    gateway = build_gateway(spec, sandbox=True, credentials=credentials)
    try:
        await gateway.load_markets()
        last = await gateway.fetch_last("BTC/USDT")
        assert last > 0
        bid, ask = await gateway.fetch_top_of_book("BTC/USDT")
        assert bid <= ask
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_binance_sandbox_free_balance():
    spec, credentials = _credentials_or_skip("binance")
    gateway = build_gateway(spec, sandbox=True, credentials=credentials)
    try:
        await gateway.load_markets()
        balance = await gateway.fetch_free_balance("USDT")
        assert balance >= 0.0
    finally:
        await gateway.close()


@pytest.mark.asyncio
async def test_bybit_sandbox_markets():
    spec, credentials = _credentials_or_skip("bybit")
    gateway = build_gateway(spec, sandbox=True, credentials=credentials)
    try:
        await gateway.load_markets()
        assert await gateway.fetch_last("BTC/USDT") > 0
    finally:
        await gateway.close()
