import pytest

from domain.exchange_types import FILLED, OPEN, PARTIALLY_FILLED
from trading.exchanges.authenticated import AuthenticatedQueries, fetch_trading_fee
from trading.exchanges.ccxt_gateway import CcxtGateway
from trading.exchanges.errors import ExchangeConfigError
from trading.exchanges.permissions import verify_key_permissions
from trading.exchanges.registry import get_spec


class FakeClient:
    def __init__(self, options=None):
        self.options = dict(options or {})
        self.markets = {"BTC/USDT": {"spot": True, "limits": {}}}
        self.balance = {"free": {"BTC": 0.5, "USDT": 100.0}}
        self.open_orders = []
        self.closed_orders = []
        self.open_args = []
        self.closed_args = []
        self.permission_payload = {}
        self.permission_error = None
        self.request_args = []
        self.api = {}

    async def load_markets(self):
        return self.markets

    async def fetch_balance(self):
        return self.balance

    async def fetch_open_orders(self, symbol, since=None, limit=None):
        self.open_args.append({"symbol": symbol, "since": since})
        return list(self.open_orders)

    async def fetch_closed_orders(self, symbol, since=None, limit=None):
        self.closed_args.append({"symbol": symbol, "since": since})
        return list(self.closed_orders)

    async def fetch_trading_fee(self, symbol):
        return {"symbol": symbol, "maker": 0.001, "taker": 0.002}

    async def request(self, path, section=None, method="GET", params=None, config=None):
        self.request_args.append(
            {"path": path, "section": section, "method": method, "params": params}
        )
        if self.permission_error is not None:
            raise self.permission_error
        return self.permission_payload

    def describe(self):
        return {"id": "fake", "api": self.api}

    def has(self):
        return {"fetchTradingFee": True}

    async def close(self):
        return None


@pytest.fixture
def fake_ccxt(monkeypatch):
    created = {}

    class FakeExchangeClass:
        def __new__(cls, options=None):
            client = FakeClient(options)
            created["client"] = client
            return client

    class FakeCcxtAsync:
        NotSupported = type("NotSupported", (Exception,), {})

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return FakeExchangeClass

    import trading.exchanges.ccxt_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "ccxt_async", FakeCcxtAsync())
    return created


@pytest.mark.asyncio
async def test_fetch_free_balance(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    queries = AuthenticatedQueries(gateway)
    assert await queries.fetch_free_balance("BTC") == 0.5
    await gateway.close()


@pytest.mark.asyncio
async def test_fetch_free_balance_missing_currency_is_zero(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    queries = AuthenticatedQueries(gateway)
    assert await queries.fetch_free_balance("DOGE") == 0.0
    await gateway.close()


@pytest.mark.asyncio
async def test_find_order_in_open_orders(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    fake_ccxt["client"].open_orders = [
        {"id": "o1", "clientOrderId": "cid-1", "status": "open", "amount": 1.0, "filled": 0.2}
    ]
    snapshot = await gateway.fetch_order_by_client_id("BTC/USDT", "cid-1")
    assert snapshot is not None
    assert snapshot.exchange_order_id == "o1"
    assert snapshot.status == PARTIALLY_FILLED
    assert snapshot.filled == pytest.approx(0.2)
    await gateway.close()


@pytest.mark.asyncio
async def test_find_order_in_closed_orders_uses_24h_window(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    fake_ccxt["client"].closed_orders = [
        {
            "id": "o2",
            "clientOrderId": "cid-2",
            "status": "closed",
            "amount": 1.0,
            "filled": 1.0,
            "average": 50.0,
            "fee": {"cost": 0.05, "currency": "USDT"},
        }
    ]
    snapshot = await gateway.fetch_order_by_client_id("BTC/USDT", "cid-2")
    assert snapshot is not None
    assert snapshot.status == FILLED
    assert snapshot.fee_cost == pytest.approx(0.05)
    assert snapshot.fee_currency == "USDT"
    since = fake_ccxt["client"].closed_args[0]["since"]
    assert isinstance(since, int) and since > 0
    await gateway.close()


@pytest.mark.asyncio
async def test_missing_order_returns_none(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    assert await gateway.fetch_order_by_client_id("BTC/USDT", "absent") is None
    await gateway.close()


@pytest.mark.asyncio
async def test_duplicate_client_order_id_is_rejected(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    fake_ccxt["client"].open_orders = [
        {"id": "o1", "clientOrderId": "dup", "status": "open", "amount": 1.0, "filled": 0.0}
    ]
    fake_ccxt["client"].closed_orders = [
        {"id": "o2", "clientOrderId": "dup", "status": "closed", "amount": 1.0, "filled": 1.0}
    ]
    with pytest.raises(ExchangeConfigError, match="duplicate_client_order_id"):
        await gateway.fetch_order_by_client_id("BTC/USDT", "dup")
    await gateway.close()


@pytest.mark.asyncio
async def test_open_status_without_fill_stays_open(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    fake_ccxt["client"].open_orders = [
        {"id": "o1", "clientOrderId": "cid", "status": "open", "amount": 1.0, "filled": 0.0}
    ]
    snapshot = await gateway.fetch_order_by_client_id("BTC/USDT", "cid")
    assert snapshot is not None
    assert snapshot.status == OPEN
    await gateway.close()


@pytest.mark.asyncio
async def test_fetch_trading_fee(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    fee = await fetch_trading_fee(gateway, "BTC/USDT")
    assert fee["maker"] == pytest.approx(0.001)
    await gateway.close()


@pytest.mark.asyncio
async def test_fetch_trading_fee_not_supported(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    fake_ccxt["client"].has = lambda: {"fetchTradingFee": False}
    with pytest.raises(ExchangeConfigError, match="fetch_trading_fee_not_supported"):
        await fetch_trading_fee(gateway, "BTC/USDT")
    await gateway.close()


async def _gateway_with_api(monkeypatch, api):
    created = {}

    class FakeExchangeClass:
        def __new__(cls, options=None):
            client = FakeClient(options)
            client.api = api
            created["client"] = client
            return client

    class FakeCcxtAsync:
        NotSupported = type("NotSupported", (Exception,), {})

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return FakeExchangeClass

    import trading.exchanges.ccxt_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "ccxt_async", FakeCcxtAsync())
    return CcxtGateway(get_spec("binance"), sandbox=False), created


BINANCE_API = {"sapi": {"get": {"account/apiRestrictions": {"cost": 0.1}}}}


@pytest.mark.asyncio
async def test_binance_withdrawal_disabled_passes(monkeypatch):
    gateway, created = await _gateway_with_api(monkeypatch, BINANCE_API)
    client = created["client"]
    client.permission_payload = {"enableWithdrawals": False, "enableReading": True}
    ok, reason = await verify_key_permissions(gateway, get_spec("binance"))
    assert (ok, reason) == (True, "ok")
    assert client.request_args[0]["section"] == ["sapi", "get"]


@pytest.mark.asyncio
async def test_binance_withdrawal_enabled_fails(monkeypatch):
    gateway, created = await _gateway_with_api(monkeypatch, BINANCE_API)
    client = created["client"]
    client.permission_payload = {"enableWithdrawals": True}
    ok, reason = await verify_key_permissions(gateway, get_spec("binance"))
    assert (ok, reason) == (False, "withdraw_enabled_or_unknown")


@pytest.mark.asyncio
async def test_binance_missing_field_fails(monkeypatch):
    gateway, created = await _gateway_with_api(monkeypatch, BINANCE_API)
    client = created["client"]
    client.permission_payload = {"enableReading": True}
    ok, reason = await verify_key_permissions(gateway, get_spec("binance"))
    assert (ok, reason) == (False, "withdraw_enabled_or_unknown")


@pytest.mark.asyncio
async def test_permission_request_error_is_reported(monkeypatch):
    gateway, created = await _gateway_with_api(monkeypatch, BINANCE_API)
    client = created["client"]
    client.permission_error = RuntimeError("boom SUPER_SECRET")
    ok, reason = await verify_key_permissions(gateway, get_spec("binance"))
    assert (ok, reason) == (False, "permission_check_failed")


@pytest.mark.asyncio
async def test_missing_endpoint_requires_attestation_only():
    gateway, _ = await _gateway_with_no_api()
    ok, reason = await verify_key_permissions(gateway, get_spec("kraken"))
    assert (ok, reason) == (True, "no_endpoint_attestation_required")


async def _gateway_with_no_api():
    class Client(FakeClient):
        pass

    gateway = object.__new__(CcxtGateway)
    gateway.spec = get_spec("kraken")
    gateway.exchange_id = "kraken"
    gateway.sandbox = False
    gateway._secrets = []
    gateway._credentials = None
    gateway.client = Client()
    gateway._markets_loaded = False
    return gateway, gateway.client


@pytest.mark.asyncio
async def test_attestation_alone_is_not_enough_when_endpoint_exists(monkeypatch):
    gateway, created = await _gateway_with_api(monkeypatch, BINANCE_API)
    client = created["client"]
    client.permission_payload = {"enableWithdrawals": True}
    ok, _ = await verify_key_permissions(gateway, get_spec("binance"))
    assert ok is False


@pytest.mark.asyncio
async def test_lbank_rule_stays_undefined(monkeypatch):
    lbank_api = {"spot": {"private": {"post": {"supplement/api_Restrictions": {"cost": 2.5}}}}}

    created = {}

    class FakeExchangeClass:
        def __new__(cls, options=None):
            client = FakeClient(options)
            client.api = lbank_api
            created["client"] = client
            return client

    class FakeCcxtAsync:
        NotSupported = type("NotSupported", (Exception,), {})

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return FakeExchangeClass

    import trading.exchanges.ccxt_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "ccxt_async", FakeCcxtAsync())
    gateway = CcxtGateway(get_spec("lbank"), sandbox=False)
    ok, reason = await verify_key_permissions(gateway, get_spec("lbank"))
    assert (ok, reason) == (False, "lbank_rule_not_defined")


class _DescribeClient:
    def __init__(self, api):
        self._api = api

    def describe(self):
        return {"id": "x", "api": self._api}


def test_resolves_binance_flat_verb_shape():
    from trading.exchanges.permissions import _resolve

    api = {"sapi": {"get": {"account/apiRestrictions": {"cost": 0.1}}}}
    resolved = _resolve(_DescribeClient(api), "sapi/v1/account/apiRestrictions")
    assert resolved == (["sapi", "get"], "GET", "account/apiRestrictions")


def test_resolves_lbank_nested_verb_shape():
    from trading.exchanges.permissions import _resolve

    api = {"spot": {"private": {"post": {"supplement/api_Restrictions": {"cost": 2.5}}}}}
    resolved = _resolve(_DescribeClient(api), "supplement/api_Restrictions")
    assert resolved == (["spot", "private", "post"], "POST", "supplement/api_Restrictions")


def test_resolves_direct_section_verb_shape():
    from trading.exchanges.permissions import _resolve

    api = {"get": {"ticker": {}}}
    resolved = _resolve(_DescribeClient(api), "ticker")
    assert resolved == (["get"], "GET", "ticker")
