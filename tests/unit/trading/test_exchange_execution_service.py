from datetime import UTC, datetime

import pytest

from domain.exchange_types import (
    FILLED,
    REJECTED,
    SHADOW,
    SUBMITTED,
    OrderSnapshot,
    PlacementResult,
)
from trading.exchanges.execution_service import (
    ExchangeExecutionService,
    make_client_order_id,
)
from trading.exchanges.gate_inputs import ExchangeSettings
from trading.live_ledger import LiveLedger


def _settings(**overrides) -> ExchangeSettings:
    base = dict(
        enabled=("binance",),
        access_profile="general",
        sandbox=True,
        shadow_mode=False,
        live_enabled=False,
        live_review_id="",
        attested_keys=(),
        symbol_allowlist=("BTC/USDT",),
        max_order_notional=50.0,
        max_daily_notional=200.0,
        max_deviation_pct=2.0,
        max_spread_pct=0.5,
        ledger_path="runs/live_ledger.db",
        reconcile_interval_seconds=60.0,
        unknown_after_seconds=120.0,
        request_timeout_ms=15000,
    )
    base.update(overrides)
    return ExchangeSettings(**base)


class FakeGateway:
    def __init__(
        self,
        last=50_000.0,
        bid=49_990.0,
        ask=50_010.0,
        order_result=None,
        order_error=None,
        balance=1.0,
        limits=(0.0001, 5.0),
        snapshot=None,
    ):
        self.exchange_id = "binance"
        self.last = last
        self.bid = bid
        self.ask = ask
        self.order_result = order_result or PlacementResult(accepted=True, exchange_order_id="ex-1")
        self.order_error = order_error
        self.balance = balance
        self._limits = limits
        self.snapshot = snapshot
        self.placed = 0
        self.closed = False
        self.loaded = 0
        self.secrets_seen = []

    async def load_markets(self):
        self.loaded += 1

    async def fetch_last(self, symbol):
        return self.last

    async def fetch_top_of_book(self, symbol):
        return self.bid, self.ask

    async def normalize(self, symbol, amount, price):
        return float(amount), float(price)

    def market_limits(self, symbol):
        return self._limits

    async def place_limit_order(self, intent):
        self.placed += 1
        if self.order_error is not None:
            raise self.order_error
        return self.order_result

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        return self.snapshot

    async def fetch_free_balance(self, currency):
        return self.balance

    def error_text(self, exc):
        return str(exc)

    async def close(self):
        self.closed = True


class Factory:
    def __init__(self, gateway):
        self.gateway = gateway
        self.calls = 0

    def __call__(self, spec, sandbox, credentials):
        self.calls += 1
        self.last_credentials = credentials
        self.last_sandbox = sandbox
        return self.gateway


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="fake-key", api_secret="fake-secret")
    monkeypatch.setattr(
        "trading.exchanges.execution_service.credentials_usable",
        lambda spec, sandbox: (True, credentials.as_list()),
    )
    monkeypatch.setattr(
        "trading.exchanges.execution_service.load_exchange_credentials",
        lambda spec, sandbox: credentials,
    )
    return credentials


def _service(gateway, ledger, settings=None, notify=None):
    return ExchangeExecutionService(
        settings=settings or _settings(),
        ledger=ledger,
        gateway_factory=Factory(gateway),
        notify=notify,
        execution_dry_run=True,
    )


@pytest.mark.asyncio
async def test_sandbox_order_is_submitted(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "sandbox"
    assert result.status == SUBMITTED
    assert gateway.placed == 1
    row = await ledger.get_row(result.client_order_id, "binance")
    assert row["status"] == SUBMITTED
    assert row["exchange_order_id"] == "ex-1"
    assert gateway.closed is True


@pytest.mark.asyncio
async def test_client_order_id_is_deterministic():
    first = make_client_order_id("binance", "sig-1")
    second = make_client_order_id("binance", "sig-1")
    assert first == second
    assert len(first) == 32
    assert all(ch in "0123456789abcdef" for ch in first)


@pytest.mark.asyncio
async def test_duplicate_signal_does_not_place_second_order(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger)
    first = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert first.ok is True
    second = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert second.ok is False
    assert second.reason == "duplicate_signal"
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_halt_refuses_everything(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger)
    await service.halt()
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "halted"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_disabled_exchange_is_refused(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger, _settings(enabled=()))
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "exchange_not_enabled"


@pytest.mark.asyncio
async def test_unknown_exchange_is_refused(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger)
    result = await service.submit_signal("nope", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "unknown_exchange"


@pytest.mark.asyncio
async def test_iran_venue_refused_under_general_profile(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger, _settings(enabled=("lbank",)))
    result = await service.submit_signal("lbank", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "scope_mismatch"


@pytest.mark.asyncio
async def test_symbol_not_allowlisted(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger, _settings(symbol_allowlist=()))
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "symbol_not_allowlisted"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_price_deviation_refused(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 52_000.0)
    assert result.reason == "price_deviation_exceeded"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_spread_refused(ledger):
    gateway = FakeGateway(bid=49_000.0, ask=51_000.0)
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "spread_exceeded"


@pytest.mark.asyncio
async def test_sell_without_balance_refused(ledger):
    gateway = FakeGateway(balance=0.0001)
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "sell", 0.0005, 50_000.0)
    assert result.reason == "insufficient_base_balance"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_daily_notional_refused(ledger):
    gateway = FakeGateway()
    service = _service(
        gateway, ledger, _settings(max_daily_notional=40.0, max_order_notional=200.0)
    )
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.001, 50_000.0)
    assert result.reason == "daily_notional_exceeded"


@pytest.mark.asyncio
async def test_venue_rejection_is_recorded(ledger):
    gateway = FakeGateway(order_result=PlacementResult(accepted=False, error="InvalidOrder: bad"))
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    row = await ledger.get_row(result.client_order_id, "binance")
    assert row["status"] == REJECTED
    assert "InvalidOrder" in row["reason"]


@pytest.mark.asyncio
async def test_missing_order_id_is_rejected(ledger):
    gateway = FakeGateway(order_result=PlacementResult(accepted=False, error="missing_order_id"))
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "missing_order_id"
    row = await ledger.get_row(result.client_order_id, "binance")
    assert row["status"] == REJECTED


@pytest.mark.asyncio
async def test_network_error_leaves_row_pending(ledger):
    gateway = FakeGateway(order_error=TimeoutError("timed out"))
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.reason == "pending_reconcile"
    row = await ledger.get_row(result.client_order_id, "binance")
    assert row["status"] == "pending_submit"
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_shadow_places_no_order(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger, _settings(sandbox=False, shadow_mode=True))
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "shadow"
    assert result.status == SHADOW
    assert gateway.placed == 0
    row = await ledger.get_row(result.client_order_id, "binance")
    assert row["status"] == SHADOW


@pytest.mark.asyncio
async def test_live_defaults_never_send(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger, _settings(sandbox=False, shadow_mode=False))
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.mode != "live"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_credentials_missing_refused(ledger, monkeypatch):
    monkeypatch.setattr(
        "trading.exchanges.execution_service.credentials_usable",
        lambda spec, sandbox: (False, []),
    )
    gateway = FakeGateway()
    service = _service(gateway, ledger)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "credentials_missing"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_ourbit_gateway_error_is_refused(ledger):
    from trading.exchanges.errors import OurbitNotReady

    def failing_factory(spec, sandbox, credentials):
        raise OurbitNotReady("ourbit_endpoints_not_documented")

    service = ExchangeExecutionService(
        settings=_settings(enabled=("ourbit",), access_profile="iran"),
        ledger=ledger,
        gateway_factory=failing_factory,
        execution_dry_run=True,
    )
    result = await service.submit_signal("ourbit", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.reason == "exchange_not_ready"


@pytest.mark.asyncio
async def test_gateway_is_closed_on_error(ledger):
    gateway = FakeGateway(bid=0.0)
    service = _service(gateway, ledger)
    await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert gateway.closed is True


@pytest.mark.asyncio
async def test_notify_receives_sanitized_text(ledger, monkeypatch):
    notices = []

    async def notify(text):
        notices.append(text)

    monkeypatch.setattr(
        "trading.exchanges.execution_service.credentials_usable",
        lambda spec, sandbox: (True, ["TOPSECRET"]),
    )
    gateway = FakeGateway(order_result=PlacementResult(accepted=False, error="bad TOPSECRET value"))
    service = _service(gateway, ledger, notify=notify)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert "TOPSECRET" not in result.reason
    assert all("TOPSECRET" not in text for text in notices)


def test_snapshot_status_is_terminal():
    snapshot = OrderSnapshot("ex", "cid", FILLED, 0.0, 0.0, 0.0, "")
    assert snapshot.status == FILLED
    assert datetime.now(UTC).tzinfo is not None


@pytest.mark.asyncio
async def test_shadow_never_calls_place_limit_order_counter(ledger):
    gateway = FakeGateway()
    service = _service(gateway, ledger, _settings(sandbox=False, shadow_mode=True))
    for index in range(5):
        result = await service.submit_signal(
            "binance", f"sig-{index}", "BTC/USDT", "buy", 0.0005, 50_000.0
        )
        assert result.ok is True
        assert result.mode == "shadow"
    assert gateway.placed == 0
    rows = await ledger.get_shadow_rows()
    assert len(rows) == 5
    assert all(row["status"] == SHADOW for row in rows)
