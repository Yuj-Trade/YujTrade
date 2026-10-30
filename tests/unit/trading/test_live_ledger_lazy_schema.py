import pytest

from domain.exchange_types import PENDING_SUBMIT, OrderIntent
from trading.live_ledger import LiveLedger


def _intent(signal_id="sig-1", client_order_id="cid-1"):
    return OrderIntent(
        exchange_id="binance",
        signal_id=signal_id,
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_000.0,
        client_order_id=client_order_id,
        sandbox=True,
    )


@pytest.fixture
def fresh_ledger(tmp_path):
    return LiveLedger(tmp_path / "lazy.db")


@pytest.mark.asyncio
async def test_get_control_on_a_fresh_ledger_returns_default(fresh_ledger):
    assert await fresh_ledger.get_control("halted", "0") == "0"


@pytest.mark.asyncio
async def test_set_and_get_control_without_initialize(fresh_ledger):
    await fresh_ledger.set_control("halted", "1")
    assert await fresh_ledger.get_control("halted", "0") == "1"


@pytest.mark.asyncio
async def test_append_pending_without_initialize(fresh_ledger):
    assert await fresh_ledger.append_pending(_intent(), "sandbox") is True
    row = await fresh_ledger.get_row("cid-1", "binance")
    assert row is not None
    assert row["status"] == PENDING_SUBMIT


@pytest.mark.asyncio
async def test_duplicate_after_lazy_schema_still_refused(fresh_ledger):
    assert await fresh_ledger.append_pending(_intent(), "sandbox") is True
    assert await fresh_ledger.append_pending(_intent(), "sandbox") is False


@pytest.mark.asyncio
async def test_initialize_remains_idempotent(fresh_ledger):
    await fresh_ledger.initialize()
    await fresh_ledger.initialize()
    assert await fresh_ledger.append_pending(_intent(), "sandbox") is True


@pytest.mark.asyncio
async def test_initialize_after_lazy_use_keeps_data(fresh_ledger):
    await fresh_ledger.append_pending(_intent(), "sandbox")
    await fresh_ledger.initialize()
    row = await fresh_ledger.get_row("cid-1", "binance")
    assert row is not None


@pytest.mark.asyncio
async def test_halt_on_a_fresh_ledger_records_the_flag(tmp_path):
    from trading.exchanges.execution_service import ExchangeExecutionService
    from trading.exchanges.gate_inputs import ExchangeSettings

    ledger = LiveLedger(tmp_path / "halt.db")
    settings = ExchangeSettings(
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
        ledger_path=str(tmp_path / "halt.db"),
        reconcile_interval_seconds=60.0,
        unknown_after_seconds=120.0,
        request_timeout_ms=15000,
    )
    service = ExchangeExecutionService(
        settings=settings,
        ledger=ledger,
        gateway_factory=lambda spec, sandbox, creds: None,
    )
    await service.halt()
    assert await ledger.get_control("halted", "0") == "1"


@pytest.mark.asyncio
async def test_halt_blocks_submission_on_fresh_ledger(tmp_path):
    from trading.exchanges.execution_service import ExchangeExecutionService
    from trading.exchanges.gate_inputs import ExchangeSettings

    ledger = LiveLedger(tmp_path / "halt2.db")
    settings = ExchangeSettings(
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
        ledger_path=str(tmp_path / "halt2.db"),
        reconcile_interval_seconds=60.0,
        unknown_after_seconds=120.0,
        request_timeout_ms=15000,
    )
    service = ExchangeExecutionService(
        settings=settings,
        ledger=ledger,
        gateway_factory=lambda spec, sandbox, creds: None,
    )
    await service.halt()
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.reason == "halted"
