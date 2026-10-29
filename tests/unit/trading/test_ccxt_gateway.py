import pytest

from trading.exchanges.ccxt_gateway import CcxtGateway
from trading.exchanges.credentials import ExchangeCredentials
from trading.exchanges.errors import ExchangeConfigError, OurbitNotReady
from trading.exchanges.factory import build_gateway
from trading.exchanges.registry import get_spec


class FakeClient:
    def __init__(self, options=None):
        self.options = dict(options or {})
        self.apiKey = self.options.get("apiKey")
        self.secret = self.options.get("secret")
        self.password = self.options.get("password")
        self.markets = {
            "BTC/USDT": {"spot": True, "limits": {"amount": {"min": 0.0001}, "cost": {"min": 5.0}}},
            "BTC/USDT:USDT": {"spot": False, "limits": {}},
        }
        self.closed = False
        self.sandbox_requests = []
        self.raise_sandbox = False
        self.ticker = {"last": 50_000.0, "close": 49_900.0}
        self.book = {"bids": [[49_990.0, 1.0]], "asks": [[50_010.0, 1.0]]}
        self.closed_calls = 0

    async def load_markets(self):
        return self.markets

    async def fetch_ticker(self, symbol):
        return self.ticker

    async def fetch_order_book(self, symbol, limit=None):
        return self.book

    def amount_to_precision(self, symbol, amount):
        return f"{round(amount, 6):.6f}"

    def price_to_precision(self, symbol, price):
        return f"{round(price, 2):.2f}"

    def set_sandbox_mode(self, enabled):
        if self.raise_sandbox:
            raise TypeError("'NoneType' object is not iterable")
        self.sandbox_requests.append(enabled)

    def describe(self):
        return {"id": "fake", "api": {}}

    def has(self):
        return {}

    async def close(self):
        self.closed = True
        self.closed_calls += 1


@pytest.fixture
def fake_ccxt(monkeypatch):
    created = {}

    class FakeExchangeClass:
        def __new__(cls, options=None):
            client = FakeClient(options)
            created["client"] = client
            return client

        @staticmethod
        def describe():
            return {"id": "fake", "api": {}}

    import trading.exchanges.ccxt_gateway as gateway_module

    class FakeCcxtAsync:
        NotSupported = type("NotSupported", (Exception,), {})

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return FakeExchangeClass

    monkeypatch.setattr(gateway_module, "ccxt_async", FakeCcxtAsync())
    return created


@pytest.mark.asyncio
async def test_load_markets_and_fetch_last(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    assert await gateway.fetch_last("BTC/USDT") == 50_000.0
    await gateway.close()
    assert fake_ccxt["client"].closed is True


@pytest.mark.asyncio
async def test_non_spot_symbol_is_rejected(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    with pytest.raises(ExchangeConfigError):
        await gateway.fetch_last("BTC/USDT:USDT")
    await gateway.close()


@pytest.mark.asyncio
async def test_unknown_symbol_is_rejected(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    with pytest.raises(ExchangeConfigError):
        await gateway.fetch_top_of_book("DOGE/USDT")
    await gateway.close()


@pytest.mark.asyncio
async def test_zero_last_price_is_rejected(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    fake_ccxt["client"].ticker = {"last": None, "close": None}
    with pytest.raises(ExchangeConfigError):
        await gateway.fetch_last("BTC/USDT")
    await gateway.close()


@pytest.mark.asyncio
async def test_empty_book_is_rejected(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    fake_ccxt["client"].book = {"bids": [], "asks": []}
    with pytest.raises(ExchangeConfigError):
        await gateway.fetch_top_of_book("BTC/USDT")
    await gateway.close()


@pytest.mark.asyncio
async def test_top_of_book(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    assert await gateway.fetch_top_of_book("BTC/USDT") == (49_990.0, 50_010.0)
    await gateway.close()


@pytest.mark.asyncio
async def test_normalize_uses_exchange_precision(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    amount, price = await gateway.normalize("BTC/USDT", 0.0123456789, 50000.9876)
    assert amount == pytest.approx(0.012346)
    assert price == pytest.approx(50000.99)
    await gateway.close()


@pytest.mark.asyncio
async def test_market_limits(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)
    await gateway.load_markets()
    assert gateway.market_limits("BTC/USDT") == (0.0001, 5.0)
    await gateway.close()


@pytest.mark.asyncio
async def test_sandbox_mode_is_requested(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=True)
    assert fake_ccxt["client"].sandbox_requests == [True]
    await gateway.close()


@pytest.mark.asyncio
async def test_sandbox_not_supported_raises_config_error(fake_ccxt, monkeypatch):
    original = FakeClient.set_sandbox_mode

    def exploding(self, enabled):
        raise TypeError("'NoneType' object is not iterable")

    monkeypatch.setattr(FakeClient, "set_sandbox_mode", exploding)
    try:
        with pytest.raises(ExchangeConfigError, match="sandbox_not_supported"):
            CcxtGateway(get_spec("kucoin"), sandbox=True)
    finally:
        monkeypatch.setattr(FakeClient, "set_sandbox_mode", original)


@pytest.mark.asyncio
async def test_credentials_are_passed_to_client(fake_ccxt):
    credentials = ExchangeCredentials(api_key="k", api_secret="s", passphrase="p")
    CcxtGateway(get_spec("okx"), sandbox=False, credentials=credentials)
    client = fake_ccxt["client"]
    assert client.apiKey == "k"
    assert client.secret == "s"
    assert client.password == "p"


@pytest.mark.asyncio
async def test_close_is_safe_on_error(fake_ccxt):
    gateway = CcxtGateway(get_spec("binance"), sandbox=False)

    async def boom():
        raise RuntimeError("socket closed")

    fake_ccxt["client"].close = boom
    with pytest.raises(RuntimeError):
        await gateway.close()


def test_factory_builds_ccxt_gateway(fake_ccxt):
    gateway = build_gateway(get_spec("binance"), sandbox=False)
    assert gateway.exchange_id == "binance"


def test_factory_raises_for_ourbit(fake_ccxt):
    with pytest.raises(OurbitNotReady):
        build_gateway(get_spec("ourbit"), sandbox=False)


def test_gateway_without_ccxt_class_is_rejected():
    from trading.exchanges.registry import ExchangeSpec

    spec = ExchangeSpec(
        "synthetic", "Synthetic", None, "general", "ready", True, False, "plain", None, None
    )
    with pytest.raises(ExchangeConfigError):
        CcxtGateway(spec, sandbox=False)


@pytest.mark.asyncio
async def test_error_text_redacts_secrets(fake_ccxt):
    credentials = ExchangeCredentials(api_key="SUPER_KEY", api_secret="SUPER_SECRET")
    gateway = CcxtGateway(get_spec("bybit"), sandbox=False, credentials=credentials)
    text = gateway.error_text(RuntimeError("bad SUPER_KEY and SUPER_SECRET"))
    assert "SUPER_KEY" not in text
    assert "SUPER_SECRET" not in text
    await gateway.close()


class CreateOrderClient(FakeClient):
    def __init__(self, options=None):
        super().__init__(options)
        self.create_response = {
            "id": "ex-9",
            "status": "open",
            "fee": {"cost": 0.01, "currency": "USDT"},
        }
        self.create_error = None
        self.create_args = []

    async def create_order(self, symbol, order_type, side, amount, price, params=None):
        self.create_args.append(
            {
                "symbol": symbol,
                "order_type": order_type,
                "side": side,
                "amount": amount,
                "price": price,
                "params": params,
            }
        )
        if self.create_error is not None:
            raise self.create_error
        return self.create_response


def _create_gateway(monkeypatch, spec_id="binance", client=None):
    created = {}
    holder = client if client is not None else CreateOrderClient()

    class FakeExchangeClass:
        @staticmethod
        def describe():
            return {"id": "fake", "api": {}}

        def __new__(cls, options=None):
            created["client"] = holder
            return holder

    class FakeCcxtAsync:
        class NetworkError(Exception):
            pass

        class ExchangeError(Exception):
            pass

        NotSupported = type("NotSupported", (Exception,), {})

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return FakeExchangeClass

    import trading.exchanges.ccxt_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "ccxt_async", FakeCcxtAsync())
    return CcxtGateway(get_spec(spec_id), sandbox=False), holder


def _intent(**overrides):
    from domain.exchange_types import OrderIntent

    base = dict(
        exchange_id="binance",
        signal_id="s1",
        symbol="BTC/USDT",
        side="buy",
        amount=0.001,
        price=50_000.0,
        client_order_id="abcdef0123456789abcdef0123456789",
        sandbox=False,
    )
    base.update(overrides)
    return OrderIntent(**base)


@pytest.mark.asyncio
async def test_place_limit_order_returns_exchange_id(monkeypatch):
    gateway, client = _create_gateway(monkeypatch)
    await gateway.load_markets()
    result = await gateway.place_limit_order(_intent())
    assert result.accepted is True
    assert result.exchange_order_id == "ex-9"
    assert result.fee_cost == pytest.approx(0.01)
    assert result.fee_currency == "USDT"
    sent = client.create_args[0]
    assert sent["order_type"] == "limit"
    assert sent["side"] == "buy"
    assert sent["params"]["clientOrderId"] == "abcdef0123456789abcdef0123456789"
    await gateway.close()


@pytest.mark.asyncio
async def test_place_limit_order_missing_id_is_rejected(monkeypatch):
    client = CreateOrderClient()
    client.create_response = {"status": "open"}
    gateway, _ = _create_gateway(monkeypatch, client=client)
    await gateway.load_markets()
    result = await gateway.place_limit_order(_intent())
    assert result.accepted is False
    assert result.error == "missing_order_id"
    await gateway.close()


@pytest.mark.asyncio
async def test_place_limit_order_exchange_error_is_rejected(monkeypatch):
    import trading.exchanges.ccxt_gateway as gateway_module

    client = CreateOrderClient()
    gateway, _ = _create_gateway(monkeypatch, client=client)
    client.create_error = gateway_module.ccxt_async.ExchangeError("InvalidOrder")
    await gateway.load_markets()
    result = await gateway.place_limit_order(_intent())
    assert result.accepted is False
    assert "InvalidOrder" in result.error
    await gateway.close()


@pytest.mark.asyncio
async def test_place_limit_order_network_error_propagates(monkeypatch):
    import trading.exchanges.ccxt_gateway as gateway_module

    client = CreateOrderClient()
    gateway, _ = _create_gateway(monkeypatch, client=client)
    client.create_error = gateway_module.ccxt_async.NetworkError("timeout")
    await gateway.load_markets()
    with pytest.raises(gateway_module.ccxt_async.NetworkError):
        await gateway.place_limit_order(_intent())
    await gateway.close()


@pytest.mark.asyncio
async def test_place_limit_order_rejects_invalid_side(monkeypatch):
    gateway, _ = _create_gateway(monkeypatch)
    await gateway.load_markets()
    result = await gateway.place_limit_order(_intent(side="hold"))
    assert result.accepted is False
    assert result.error == "invalid_side"
    await gateway.close()


@pytest.mark.asyncio
async def test_place_limit_order_rejects_sandbox_mismatch(monkeypatch):
    gateway, _ = _create_gateway(monkeypatch)
    await gateway.load_markets()
    result = await gateway.place_limit_order(_intent(sandbox=True))
    assert result.accepted is False
    assert result.error == "sandbox_mismatch"
    await gateway.close()


@pytest.mark.asyncio
async def test_kraken_uses_userref(monkeypatch):
    gateway, client = _create_gateway(monkeypatch, spec_id="kraken")
    await gateway.load_markets()
    await gateway.place_limit_order(_intent(exchange_id="kraken", signal_id="signal12345678"))
    assert client.create_args[0]["params"] == {"userref": "signal12"}
    await gateway.close()


@pytest.mark.asyncio
async def test_lbank_uses_custom_id(monkeypatch):
    gateway, client = _create_gateway(monkeypatch, spec_id="lbank")
    await gateway.load_markets()
    await gateway.place_limit_order(_intent(exchange_id="lbank"))
    assert client.create_args[0]["params"] == {"custom_id": "abcdef0123456789abcdef0123456789"}
    await gateway.close()
