import asyncio
from datetime import UTC, datetime

import pytest

from domain.exchange_types import (
    FILLED,
    SHADOW,
    SUBMITTED,
    UNKNOWN,
    OrderIntent,
    OrderSnapshot,
    PlacementResult,
)
from trading.exchanges.execution_service import ExchangeExecutionService
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
    def __init__(self, snapshot=None, fail=False):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec("binance")
        self.exchange_id = "binance"
        self.snapshot = snapshot
        self.fail = fail
        self.placed = 0
        self.closed = 0
        from trading.exchanges.credentials import ExchangeCredentials

        self._credentials = ExchangeCredentials(api_key="k", api_secret="s")

    async def load_markets(self):
        return None

    async def fetch_last(self, symbol):
        return 50_000.0

    async def fetch_top_of_book(self, symbol):
        return 49_990.0, 50_010.0

    async def normalize(self, symbol, amount, price):
        return float(amount), float(price)

    def market_limits(self, symbol):
        return 0.0001, 1.0

    async def fetch_free_balance(self, currency):
        return 1.0

    async def place_limit_order(self, intent):
        self.placed += 1
        return PlacementResult(accepted=True, exchange_order_id="ex-1")

    async def fetch_order_by_exchange_id(self, symbol, exchange_order_id):
        if self.fail:
            raise RuntimeError("venue down")
        return self.snapshot

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        if self.fail:
            raise RuntimeError("venue down")
        return self.snapshot

    def error_text(self, exc):
        return str(exc)

    async def close(self):
        self.closed += 1


def _service(ledger, gateway, settings=None, notify=None, monkeypatch=None):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    async def permission_check(spec):
        return True

    import trading.exchanges.credentials as credentials_module
    import trading.exchanges.execution_service as module

    module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())
    module.load_exchange_credentials = lambda spec, sandbox: credentials
    credentials_module.load_exchange_credentials = lambda spec, sandbox: credentials

    def factory(spec, sandbox, creds):
        if gateway.fail and getattr(gateway, "fail_on_construct", False):
            raise RuntimeError("construct failed")
        return gateway

    return ExchangeExecutionService(
        settings=settings or _settings(),
        ledger=ledger,
        gateway_factory=factory,
        notify=notify,
        permission_check=permission_check,
        review_ok=True,
    )


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


@pytest.mark.asyncio
async def test_sandbox_submission_requires_reconciliation(ledger):
    gateway = FakeGateway()
    service = _service(ledger, gateway)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.reason.startswith("reconciliation_pending")
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_live_submission_requires_reconciliation(ledger):
    settings = _settings(
        sandbox=False, shadow_mode=False, live_enabled=True, attested_keys=("binance",)
    )
    gateway = FakeGateway()
    service = _service(ledger, gateway, settings)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.mode != "live"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_shadow_is_not_blocked_before_reconciliation(ledger):
    settings = _settings(sandbox=False, shadow_mode=True)
    gateway = FakeGateway()
    service = _service(ledger, gateway, settings)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "shadow"
    assert result.status == SHADOW


@pytest.mark.asyncio
async def test_submission_allowed_after_successful_reconciliation(ledger):
    gateway = FakeGateway()
    service = _service(ledger, gateway)
    changed = await service.reconcile()
    assert changed == []
    assert service.reconciled is True
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "sandbox"
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_gateway_failure_keeps_service_unreconciled(ledger, monkeypatch):
    def broken_factory(spec, sandbox, creds):
        raise RuntimeError("construct failed")

    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=broken_factory,
    )
    await service.reconcile()
    assert service.reconciled is False


@pytest.mark.asyncio
async def test_reconciliation_moves_submitted_to_filled(ledger):
    intent = OrderIntent(
        exchange_id="binance",
        signal_id="sig-1",
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_000.0,
        client_order_id="cid-1",
        sandbox=True,
    )
    await ledger.append_pending(intent, "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    await ledger.set_exchange_order_id("cid-1", "binance", "ex-1")
    gateway = FakeGateway(
        snapshot=OrderSnapshot("ex-1", "", FILLED, 0.0005, 50_000.0, 0.01, "USDT")
    )
    service = _service(ledger, gateway)
    changed = await service.reconcile()
    assert changed == ["cid-1"]
    assert service.reconciled is True
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == FILLED
    assert gateway.closed >= 1


@pytest.mark.asyncio
async def test_unknown_notification_is_sent_once(ledger):
    intent = OrderIntent(
        exchange_id="binance",
        signal_id="sig-1",
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_000.0,
        client_order_id="cid-1",
        sandbox=True,
    )
    await ledger.append_pending(intent, "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    notices = []

    async def notify(text):
        notices.append(text)

    gateway = FakeGateway(snapshot=None)
    service = _service(ledger, gateway, _settings(unknown_after_seconds=0.0), notify=notify)
    await service.reconcile()
    assert len([n for n in notices if "unknown" in n]) == 1
    await service.reconcile()
    assert len([n for n in notices if "unknown" in n]) == 1
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_loop_calls_reconcile(monkeypatch):
    import main as main_module

    calls = []

    class FakeService:
        async def reconcile(self):
            calls.append(1)
            return []

    app = main_module.MainApp.__new__(main_module.MainApp)
    app.shutdown_event = asyncio.Event()
    app.trading_service = type("TS", (), {"exchange_service": FakeService()})()
    app.exchange_settings = _settings(reconcile_interval_seconds=0.01)

    async def stop_soon():
        await asyncio.sleep(0.08)
        app.shutdown_event.set()

    await asyncio.gather(app._exchange_reconcile_loop(0.01), stop_soon())
    assert calls


@pytest.mark.asyncio
async def test_reconcile_loop_without_service_returns():
    import main as main_module

    app = main_module.MainApp.__new__(main_module.MainApp)
    app.shutdown_event = asyncio.Event()
    app.trading_service = type("TS", (), {"exchange_service": None})()
    await app._exchange_reconcile_loop()
    assert app.shutdown_event.is_set() is False


def test_main_has_exchange_reconcile_loop():
    import main as main_module

    assert hasattr(main_module.MainApp, "_exchange_reconcile_loop")


def test_utc_now_is_aware():
    assert datetime.now(UTC).tzinfo is not None


@pytest.mark.asyncio
async def test_reconciliation_blocker_names_the_missing_credentials(ledger, monkeypatch):
    gateway = FakeGateway()
    service = _service(ledger, gateway)
    import trading.exchanges.credentials as credentials_module

    credentials_module.load_exchange_credentials = lambda spec, sandbox: None
    await service.reconcile()
    assert service.reconciled is False
    assert any("no_credentials:binance" in item for item in service.reconcile_blockers)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert "no_credentials:binance" in result.reason


@pytest.mark.asyncio
async def test_reconciliation_with_no_enabled_venue_reports_it(ledger):
    gateway = FakeGateway()
    service = _service(ledger, gateway, _settings(enabled=()))
    await service.reconcile()
    assert service.reconciled is False
    assert "no_enabled_exchange" in service.reconcile_blockers


@pytest.mark.asyncio
async def test_successful_pass_clears_the_blockers(ledger, monkeypatch):
    gateway = FakeGateway()
    service = _service(ledger, gateway)
    import trading.exchanges.credentials as credentials_module

    credentials_module.load_exchange_credentials = lambda spec, sandbox: None
    await service.reconcile()
    assert service.reconcile_blockers
    credentials_module.load_exchange_credentials = lambda spec, sandbox: __import__(
        "trading.exchanges.credentials", fromlist=["ExchangeCredentials"]
    ).ExchangeCredentials(api_key="k", api_secret="s")
    await service.reconcile()
    assert service.reconciled is True
    assert service.reconcile_blockers == []


@pytest.mark.asyncio
async def test_config_error_on_gateway_construction_is_counted(ledger):
    from trading.exchanges.errors import ExchangeConfigError

    def broken_factory(spec, sandbox, creds):
        raise ExchangeConfigError("sandbox_not_supported")

    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=broken_factory,
    )
    await service.reconcile()
    assert service.reconciled is False
    assert "gateway_unavailable:binance" in service.reconcile_blockers


@pytest.mark.asyncio
async def test_generic_failure_on_gateway_construction_is_counted(ledger):
    def broken_factory(spec, sandbox, creds):
        raise RuntimeError("boom")

    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=broken_factory,
    )
    await service.reconcile()
    assert service.reconciled is False
    assert "gateway_failed:binance" in service.reconcile_blockers


@pytest.mark.asyncio
async def test_scope_mismatch_is_recorded_once(ledger):
    gateway = FakeGateway()
    service = _service(ledger, gateway, _settings(enabled=("lbank",)))
    result = await service.submit_signal("lbank", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "scope_mismatch"
    counts = await ledger.refusal_counts("lbank")
    assert counts.get("scope_mismatch") == 1


@pytest.mark.asyncio
async def test_preview_gate_returns_the_reason(ledger, monkeypatch):
    gateway = FakeGateway()
    service = _service(ledger, gateway)
    assert await service.preview_gate("binance") == ("sandbox", "ok")
    assert await service.preview_gate("not-a-venue") == (None, "unknown_exchange")
    import trading.exchanges.execution_service as module

    module.credentials_usable = lambda spec, sandbox: (False, [])
    mode, reason = await service.preview_gate("binance")
    assert mode is None
    assert reason == "credentials_missing"
