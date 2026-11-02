from datetime import UTC, datetime, timedelta

import pytest

from domain.exchange_types import REJECTED, SUBMITTED, PlacementResult
from trading.exchanges.confirmation import (
    check_confirmation,
    consume_confirmation,
    issue_confirmation,
)
from trading.exchanges.execution_service import ExchangeExecutionService
from trading.exchanges.gate_inputs import ExchangeSettings
from trading.live_ledger import LiveLedger


def _live_settings(**overrides) -> ExchangeSettings:
    base = dict(
        enabled=("binance",),
        access_profile="general",
        sandbox=False,
        shadow_mode=False,
        live_enabled=True,
        live_review_id="ADR-0011",
        attested_keys=("binance",),
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


class CountingGateway:
    def __init__(self, fail_place=False):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec("binance")
        self.exchange_id = "binance"
        self.placed = 0
        self.fail_place = fail_place

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
        if self.fail_place:
            raise RuntimeError("venue rejected")
        self.placed += 1
        return PlacementResult(accepted=True, exchange_order_id="ex-1")

    async def close(self):
        return None


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


def _service(ledger, gateway, settings=None):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    async def permission_check(spec):
        return True

    def factory(spec, sandbox, creds):
        return gateway

    import trading.exchanges.execution_service as module

    module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())

    resolved = settings or _live_settings()
    service = ExchangeExecutionService(
        settings=resolved,
        ledger=ledger,
        gateway_factory=factory,
        permission_check=permission_check,
        review_ok=True,
        execution_dry_run=bool(resolved.sandbox),
    )
    service.reconciled = True
    return service


@pytest.mark.asyncio
async def test_live_without_code_issues_a_code_and_places_nothing(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    assert await service.preview_mode("binance") == "live"
    code = await service.request_confirmation("binance", "sig-1")
    assert code
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=""
    )
    assert result.ok is False
    assert result.reason == "confirmation_missing"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_wrong_code_is_refused(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    await service.request_confirmation("binance", "sig-1")
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code="BADCODE1"
    )
    assert result.ok is False
    assert result.reason == "confirmation_unknown"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_expired_code_is_refused(ledger):
    code = await issue_confirmation(ledger, "binance", "sig-1", ttl_seconds=-1.0)
    ok, reason = await check_confirmation(ledger, code, "binance", "sig-1")
    assert (ok, reason) == (False, "confirmation_expired")
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert result.reason == "confirmation_expired"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_valid_code_places_one_order(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    code = await service.request_confirmation("binance", "sig-1")
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert result.ok is True
    assert result.mode == "live"
    assert result.status == SUBMITTED
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_code_cannot_be_used_twice(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    code = await service.request_confirmation("binance", "sig-1")
    first = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert first.ok is True
    second = await service.submit_signal(
        "binance", "sig-2", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert second.ok is False
    assert second.reason == "confirmation_already_used"
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_risk_rejection_leaves_code_valid(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    code = await service.request_confirmation("binance", "sig-1")
    rejected = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 60_000.0, confirmation_code=code
    )
    assert rejected.ok is False
    assert rejected.reason == "price_deviation_exceeded"
    ok, reason = await check_confirmation(ledger, code, "binance", "sig-1")
    assert (ok, reason) == (True, "ok")
    accepted = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert accepted.ok is True
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_consumed_code_after_success_is_not_reusable(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    code = await service.request_confirmation("binance", "sig-1")
    await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    ok, reason = await consume_confirmation(ledger, code, "binance", "sig-1")
    assert (ok, reason) == (False, "confirmation_already_used")


@pytest.mark.asyncio
async def test_sandbox_needs_no_code(ledger):
    gateway = CountingGateway()
    settings = _live_settings(sandbox=True, shadow_mode=False, live_enabled=False, attested_keys=())
    service = _service(ledger, gateway, settings)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "sandbox"
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_shadow_needs_no_code(ledger):
    gateway = CountingGateway()
    settings = _live_settings(sandbox=False, shadow_mode=True)
    service = _service(ledger, gateway, settings)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "shadow"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_preview_mode_is_read_only(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    assert await service.preview_mode("binance") == "live"
    assert gateway.placed == 0
    rows = await ledger.get_non_terminal()
    assert rows == []
    assert await service.preview_mode("not-a-venue") is None


@pytest.mark.asyncio
async def test_compare_and_set_control_is_atomic(ledger):
    await ledger.set_control("k", "pending")
    assert await ledger.compare_and_set_control("k", "pending", "used") is True
    assert await ledger.compare_and_set_control("k", "pending", "used") is False
    assert await ledger.get_control("k", "") == "used"


@pytest.mark.asyncio
async def test_non_live_rejection_status_is_recorded(ledger):
    gateway = CountingGateway(fail_place=True)
    settings = _live_settings(sandbox=True, shadow_mode=False, live_enabled=False, attested_keys=())
    service = _service(ledger, gateway, settings)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.status == REJECTED
    row = await ledger.get_row(result.client_order_id, "binance")
    assert row["status"] == REJECTED


def test_utc_now_aware():
    assert datetime.now(UTC).tzinfo is not None
    assert (datetime.now(UTC) + timedelta(seconds=60)).tzinfo is not None


@pytest.mark.asyncio
async def test_code_is_consumed_before_the_row_is_written(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    code = await service.request_confirmation("binance", "sig-1")
    order: list[str] = []
    original_append = ledger.append_pending
    original_get = ledger.get_control

    async def watching_append(intent, mode, reason="", reference_price=0.0):
        order.append("append")
        return await original_append(intent, mode, reason, reference_price=reference_price)

    async def watching_get(key, default=""):
        if key.startswith("confirm:"):
            order.append("control")
        return await original_get(key, default)

    ledger.append_pending = watching_append
    ledger.get_control = watching_get
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert result.ok is True
    assert order and order[-1] == "append"
    assert "control" in order


@pytest.mark.asyncio
async def test_lost_race_does_not_write_a_row(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)
    code = await service.request_confirmation("binance", "sig-1")
    first = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert first.ok is True
    rows_before = len(await ledger.get_non_terminal())
    second = await service.submit_signal(
        "binance", "sig-2", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert second.ok is False
    assert second.reason == "confirmation_already_used"
    rows_after = len(await ledger.get_non_terminal())
    assert rows_after == rows_before
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_race_lost_reason_is_distinct(ledger):
    from trading.exchanges.confirmation import consume_confirmation

    code = await issue_confirmation(ledger, "binance", "sig-1")
    first_ok, _ = await consume_confirmation(ledger, code, "binance", "sig-1")
    assert first_ok is True
    second_ok, reason = await consume_confirmation(ledger, code, "binance", "sig-1")
    assert second_ok is False
    assert reason == "confirmation_already_used"


@pytest.mark.asyncio
async def test_consume_reports_race_lost_when_the_row_moves_underneath(ledger):
    from trading.exchanges.confirmation import consume_confirmation

    code = await issue_confirmation(ledger, "binance", "sig-1")
    key = f"confirm:{code}"
    stored = await ledger.get_control(key, "")
    parts = stored.split("|")
    parts[3] = "pending"
    original = ledger.compare_and_set_control
    calls = {"n": 0}

    async def flaky(k, expected, new):
        calls["n"] += 1
        return False

    ledger.compare_and_set_control = flaky
    ok, reason = await consume_confirmation(ledger, code, "binance", "sig-1")
    assert ok is False
    assert reason == "confirmation_race_lost"
    assert calls["n"] == 1
    ledger.compare_and_set_control = original
