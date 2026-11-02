from datetime import UTC, datetime

import pytest

from domain.exchange_types import (
    FILLED,
    REJECTED,
    SHADOW,
    SUBMITTED,
    UNKNOWN,
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
        permission_cache_seconds=600.0,
    )
    base.update(overrides)
    return ExchangeSettings(**base)


def _credentials():
    from trading.exchanges.credentials import ExchangeCredentials

    return ExchangeCredentials(api_key="k", api_secret="s")


class Venue:
    def __init__(self):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec("binance")
        self.exchange_id = "binance"
        self.last = 50_000.0
        self.placed = 0
        self.snapshots = {}

    async def load_markets(self):
        return None

    async def fetch_last(self, symbol):
        return self.last

    async def fetch_top_of_book(self, symbol):
        return self.last - 10.0, self.last + 10.0

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
        return self.snapshots.get(exchange_order_id)

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        return None

    def error_text(self, exc):
        return str(exc)

    async def close(self):
        return None


def _service(ledger, venue, settings, dry_run, permission=None):
    async def permission_check(spec):
        return True if permission is None else permission

    import trading.exchanges.credentials as credentials_module
    import trading.exchanges.execution_service as module

    credentials = _credentials()
    module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())
    module.load_exchange_credentials = lambda spec, sandbox: credentials
    credentials_module.load_exchange_credentials = lambda spec, sandbox: credentials
    service = ExchangeExecutionService(
        settings=settings,
        ledger=ledger,
        gateway_factory=lambda spec, sandbox, creds: venue,
        permission_check=permission_check,
        review_ok=True,
        execution_dry_run=dry_run,
    )
    return service


async def _ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    return instance


@pytest.mark.asyncio
async def test_end_to_end_sandbox_halt_reconcile(tmp_path):
    from domain.exchange_types import OrderSnapshot

    ledger = await _ledger(tmp_path)
    venue = Venue()
    service = _service(ledger, venue, _settings(), dry_run=True)

    assert (
        await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
        is not None
    )
    assert venue.placed == 0

    await service.reconcile()
    assert "binance" in service.reconciled_venues
    accepted = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert accepted.ok is True
    assert accepted.mode == "sandbox"
    assert venue.placed == 1

    row = await ledger.get_row(accepted.client_order_id, "binance")
    assert row["status"] == SUBMITTED
    venue.snapshots["ex-1"] = OrderSnapshot(
        "ex-1", accepted.client_order_id, FILLED, 0.0005, 50_000.0, 0.01, "USDT"
    )
    await service.reconcile()
    row = await ledger.get_row(accepted.client_order_id, "binance")
    assert row["status"] == FILLED

    await service.halt()
    blocked = await service.submit_signal("binance", "sig-2", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert blocked.reason == "halted"
    assert venue.placed == 1

    await service.resume()
    again = await service.submit_signal("binance", "sig-2", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert again.ok is True
    assert venue.placed == 2


@pytest.mark.asyncio
async def test_end_to_end_live_confirmation(tmp_path):
    ledger = await _ledger(tmp_path)
    venue = Venue()
    settings = _settings(
        sandbox=False,
        shadow_mode=False,
        live_enabled=True,
        live_review_id="ADR-0011",
        attested_keys=("binance",),
    )
    service = _service(ledger, venue, settings, dry_run=False)
    await service.reconcile()

    assert await service.preview_mode("binance") == "live"
    without_code = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0
    )
    assert without_code.ok is False
    assert without_code.reason == "confirmation_missing"

    code = await service.request_confirmation("binance", "sig-1")
    ordered = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert ordered.ok is True
    assert ordered.mode == "live"
    assert venue.placed == 1

    repeat = await service.submit_signal(
        "binance", "sig-2", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert repeat.ok is False
    assert repeat.reason == "confirmation_already_used"
    assert venue.placed == 1


@pytest.mark.asyncio
async def test_end_to_end_shadow_is_measurable(tmp_path):
    from scripts.exchange_shadow_report import build_report

    ledger = await _ledger(tmp_path)
    venue = Venue()
    settings = _settings(sandbox=False, shadow_mode=True)
    service = _service(ledger, venue, settings, dry_run=False)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_200.0)
    assert result.ok is True
    assert result.mode == "shadow"
    assert venue.placed == 0

    await ledger.record_refusal("binance", "sig-2", "exchange_not_ready")
    summary = await build_report(ledger)
    assert summary["count"] == 1
    assert summary["deviation_samples"] == 1
    assert summary["max_deviation_pct"] == pytest.approx(0.4, abs=0.01)
    assert summary["reasons"]["exchange_not_ready"] == 1
    assert summary["reasons"]["shadow"] == 1


@pytest.mark.asyncio
async def test_end_to_end_unknown_after_threshold(tmp_path):
    ledger = await _ledger(tmp_path)
    venue = Venue()
    service = _service(ledger, venue, _settings(), dry_run=True)
    await service.reconcile()
    accepted = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert accepted.ok is True
    await service.ledger.set_exchange_order_id(accepted.client_order_id, "binance", "ex-missing")
    notices = []

    async def notify(text):
        notices.append(text)

    service.notify = notify
    service.settings = _settings(unknown_after_seconds=0.0)
    await service.reconcile()
    row = await ledger.get_row(accepted.client_order_id, "binance")
    assert row["status"] == UNKNOWN
    assert any("unknown" in text for text in notices)


@pytest.mark.asyncio
async def test_end_to_end_rejected_order_is_terminal(tmp_path):
    ledger = await _ledger(tmp_path)
    venue = Venue()
    service = _service(ledger, venue, _settings(), dry_run=True)
    await service.reconcile()
    accepted = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    await service.ledger.set_status(accepted.client_order_id, "binance", REJECTED, "manual")
    assert await service.ledger.set_status(accepted.client_order_id, "binance", SUBMITTED) is False
    row = await ledger.get_row(accepted.client_order_id, "binance")
    assert row["status"] == REJECTED


@pytest.mark.asyncio
async def test_end_to_end_telegram_halt_uses_real_ledger(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.telegram_bot import TelegramBotHandler

    ledger = await _ledger(tmp_path)
    venue = Venue()
    service = _service(ledger, venue, _settings(), dry_run=True)

    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.trading_service = MagicMock()
    handler.trading_service.exchange_service = service
    handler.config_manager = MagicMock()
    handler.config_manager.get = MagicMock(return_value=None)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = []

    with patch.object(TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)):
        await handler.exchange_halt_command(update, context)

    assert await ledger.get_control("halted", "0") == "1"
    blocked = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert blocked.reason == "halted"
    assert venue.placed == 0


def test_end_to_end_date_is_aware():
    assert datetime.now(UTC).tzinfo is not None
    assert SHADOW != SUBMITTED
