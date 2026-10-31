from datetime import UTC, datetime

import pytest

from domain.exchange_types import (
    FILLED,
    PENDING_SUBMIT,
    SUBMITTED,
    UNKNOWN,
    OrderIntent,
    OrderSnapshot,
)
from trading.exchanges.execution_service import make_client_order_id
from trading.exchanges.registry import get_spec
from trading.live_ledger import LiveLedger
from trading.reconciliation import reconcile_once


class ParamsClient:
    def __init__(self):
        self.markets = {"BTC/USDT": {"spot": True, "limits": {}}}
        self.create_args = []
        self.response = {"id": "ex-1", "status": "open", "fee": {"cost": 0.0, "currency": "USDT"}}

    async def load_markets(self):
        return self.markets

    async def create_order(self, symbol, order_type, side, amount, price, params=None):
        self.create_args.append(params)
        return self.response

    async def close(self):
        return None


def _gateway(monkeypatch, exchange_id: str):
    import trading.exchanges.ccxt_gateway as gateway_module

    holder = ParamsClient()

    class FakeExchangeClass:
        class OrderNotFound(Exception):
            pass

        def __new__(cls, options=None):
            return holder

    class FakeCcxtAsync:
        class NetworkError(Exception):
            pass

        class ExchangeError(Exception):
            pass

        class OrderNotFound(Exception):
            pass

        NotSupported = type("NotSupported", (Exception,), {})

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return FakeExchangeClass

    monkeypatch.setattr(gateway_module, "ccxt_async", FakeCcxtAsync())
    gateway = gateway_module.CcxtGateway(get_spec(exchange_id), sandbox=False)
    return gateway, holder


def _intent(exchange_id: str, cid: str) -> OrderIntent:
    return OrderIntent(
        exchange_id=exchange_id,
        signal_id="SYMBOL|1h|2026-01-01T00:00:00|buy",
        symbol="BTC/USDT",
        side="buy",
        amount=0.001,
        price=50_000.0,
        client_order_id=cid,
        sandbox=False,
    )


def test_client_order_id_respects_gate_limit():
    cid = make_client_order_id("gate", "sig-1", get_spec("gate").client_id_max_len)
    assert len(cid) == 28
    assert len(cid) <= 28


def test_default_client_order_id_is_32_chars():
    assert len(make_client_order_id("binance", "sig-1")) == 32


def test_client_order_id_is_stable_per_venue_and_signal():
    assert make_client_order_id("binance", "sig-1") == make_client_order_id("binance", "sig-1")
    assert make_client_order_id("binance", "sig-1") != make_client_order_id("bybit", "sig-1")


def test_client_order_id_is_hex_only():
    cid = make_client_order_id("gate", "sig-1", 28)
    assert all(char in "0123456789abcdef" for char in cid)


@pytest.mark.asyncio
async def test_no_client_id_sent_when_not_verified(monkeypatch):
    gateway, client = _gateway(monkeypatch, "kraken")
    await gateway.load_markets()
    await gateway.place_limit_order(_intent("kraken", "abc123"))
    assert client.create_args == [{}]
    assert "userref" not in client.create_args[0]
    assert "clientOrderId" not in client.create_args[0]
    await gateway.close()


@pytest.mark.asyncio
async def test_no_client_id_sent_for_lbank(monkeypatch):
    gateway, client = _gateway(monkeypatch, "lbank")
    await gateway.load_markets()
    await gateway.place_limit_order(_intent("lbank", "abc123"))
    assert client.create_args == [{}]
    await gateway.close()


@pytest.mark.asyncio
async def test_client_id_sent_when_verified(monkeypatch):
    from dataclasses import replace

    gateway, client = _gateway(monkeypatch, "binance")
    gateway.spec = replace(gateway.spec, client_id_supported=True)
    await gateway.load_markets()
    await gateway.place_limit_order(_intent("binance", "cid-abc"))
    assert client.create_args == [{"clientOrderId": "cid-abc"}]
    await gateway.close()


def test_no_venue_is_client_id_verified_by_default():
    from trading.exchanges.registry import EXCHANGE_REGISTRY

    verified = [spec.exchange_id for spec in EXCHANGE_REGISTRY if spec.client_id_supported]
    assert verified == []


def test_registry_has_gate_limit_28():
    assert get_spec("gate").client_id_max_len == 28
    assert get_spec("binance").client_id_max_len == 32


class LookupGateway:
    def __init__(self, spec_exchange_id="binance", client_id_supported=True):
        from trading.exchanges.registry import ExchangeSpec

        self.spec = ExchangeSpec(
            exchange_id=spec_exchange_id,
            display_name=spec_exchange_id,
            ccxt_id=spec_exchange_id,
            access_scope="general",
            status="ready",
            spot_supported=True,
            needs_passphrase=False,
            secret_encoding="plain",
            sandbox_expected=None,
            permission_endpoint=None,
            client_id_supported=client_id_supported,
        )
        self.exchange_id = spec_exchange_id
        self.by_exchange_id = 0
        self.by_client_id = 0
        self.snapshot = None

    async def fetch_order_by_exchange_id(self, symbol, exchange_order_id):
        self.by_exchange_id += 1
        return self.snapshot

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        self.by_client_id += 1
        return self.snapshot

    def error_text(self, exc):
        return str(exc)


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


async def _seed(ledger, exchange_order_id="", status=SUBMITTED):
    intent = _intent("binance", "cid-1")
    intent = OrderIntent(
        exchange_id=intent.exchange_id,
        signal_id="sig-1",
        symbol=intent.symbol,
        side=intent.side,
        amount=intent.amount,
        price=intent.price,
        client_order_id=intent.client_order_id,
        sandbox=intent.sandbox,
    )
    await ledger.append_pending(intent, "sandbox")
    await ledger.set_status("cid-1", "binance", status, "seeded")
    if exchange_order_id:
        await ledger.set_exchange_order_id("cid-1", "binance", exchange_order_id)


@pytest.mark.asyncio
async def test_reconciliation_prefers_exchange_order_id(ledger):
    await _seed(ledger, exchange_order_id="ex-42")
    gateway = LookupGateway()
    gateway.snapshot = OrderSnapshot("ex-42", "cid-1", FILLED, 0.001, 50_100.0, 0.01, "USDT")
    await reconcile_once(ledger, {"binance": gateway}, 60.0)
    assert gateway.by_exchange_id == 1
    assert gateway.by_client_id == 0
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == FILLED


@pytest.mark.asyncio
async def test_reconciliation_uses_client_id_only_when_verified(ledger):
    await _seed(ledger)
    gateway = LookupGateway(client_id_supported=True)
    gateway.snapshot = OrderSnapshot("ex-42", "cid-1", FILLED, 0.001, 50_100.0, 0.0, "")
    await reconcile_once(ledger, {"binance": gateway}, 60.0)
    assert gateway.by_exchange_id == 0
    assert gateway.by_client_id == 1


@pytest.mark.asyncio
async def test_unverified_venue_never_queries_by_client_id(ledger):
    await _seed(ledger, status=PENDING_SUBMIT)
    gateway = LookupGateway(spec_exchange_id="kraken", client_id_supported=False)
    changed = await reconcile_once(ledger, {"binance": gateway}, 0.0)
    assert gateway.by_client_id == 0
    assert gateway.by_exchange_id == 0
    assert changed == ["cid-1"]
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == UNKNOWN


@pytest.mark.asyncio
async def test_snapshot_is_none_when_venue_unverified_and_no_venue_id(ledger):
    from trading.reconciliation import _fetch_snapshot

    gateway = LookupGateway(spec_exchange_id="kraken", client_id_supported=False)
    row = {"symbol": "BTC/USDT", "client_order_id": "cid-1", "exchange_order_id": ""}
    assert await _fetch_snapshot(gateway, row) is None


def test_now_utc_is_timezone_aware():
    assert datetime.now(UTC).tzinfo is not None
