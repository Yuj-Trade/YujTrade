import sqlite3

import pytest

from domain.exchange_types import SHADOW, OrderIntent
from trading.exchanges.execution_service import ExchangeExecutionService
from trading.exchanges.gate_inputs import ExchangeSettings
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
        sandbox=False,
    )


def _settings(**overrides) -> ExchangeSettings:
    base = dict(
        enabled=("binance",),
        access_profile="general",
        sandbox=False,
        shadow_mode=True,
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


def test_old_database_is_migrated_without_data_loss(tmp_path):
    path = tmp_path / "old.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE live_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL UNIQUE,
            exchange_id TEXT NOT NULL,
            client_order_id TEXT NOT NULL,
            exchange_order_id TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            amount REAL NOT NULL,
            price REAL NOT NULL,
            filled REAL NOT NULL DEFAULT 0,
            average_price REAL NOT NULL DEFAULT 0,
            fee_cost REAL NOT NULL DEFAULT 0,
            fee_currency TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('sandbox', 'live', 'shadow')),
            reason TEXT NOT NULL DEFAULT '',
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            UNIQUE (exchange_id, client_order_id)
        );
        """
    )
    legacy.execute(
        "INSERT INTO live_orders(signal_id, exchange_id, client_order_id, symbol, side, amount, "
        "price, status, mode, reason, created_at_utc, updated_at_utc) "
        "VALUES ('old-1', 'binance', 'old-cid', 'BTC/USDT', 'buy', 0.001, 50000, 'shadow', "
        "'shadow', 'shadow', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    legacy.commit()
    legacy.close()

    import asyncio

    async def run():
        ledger = LiveLedger(path)
        await ledger.initialize()
        rows = await ledger.get_shadow_rows()
        assert len(rows) == 1
        assert rows[0]["signal_id"] == "old-1"
        assert rows[0]["reference_price"] == 0.0
        assert await ledger.append_pending(_intent(), "shadow", "shadow", reference_price=50_000.0)
        fresh = await ledger.get_shadow_rows()
        assert len(fresh) == 2
        assert fresh[1]["reference_price"] == 50_000.0

    asyncio.run(run())

    verify = sqlite3.connect(path)
    columns = {row[1] for row in verify.execute("PRAGMA table_info(live_orders)")}
    verify.close()
    assert "reference_price" in columns


@pytest.mark.asyncio
async def test_refusals_are_recorded_and_counted(tmp_path):
    ledger = LiveLedger(tmp_path / "live.db")
    await ledger.initialize()
    await ledger.record_refusal("binance", "sig-1", "exchange_not_ready")
    await ledger.record_refusal("binance", "sig-2", "exchange_not_ready")
    await ledger.record_refusal("binance", "sig-3", "key_not_attested")
    counts = await ledger.refusal_counts()
    assert counts == {"exchange_not_ready": 2, "key_not_attested": 1}
    assert await ledger.refusal_counts("kraken") == {}


@pytest.mark.asyncio
async def test_shadow_row_stores_reference_price(tmp_path):
    ledger = LiveLedger(tmp_path / "live.db")
    await ledger.initialize()
    await ledger.append_pending(_intent(), "shadow", "shadow", reference_price=49_900.0)
    rows = await ledger.get_shadow_rows()
    assert rows[0]["status"] == SHADOW
    assert rows[0]["reference_price"] == pytest.approx(49_900.0)


class PassiveGateway:
    def __init__(self):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec("binance")
        self.exchange_id = "binance"

    async def load_markets(self):
        return None

    async def fetch_last(self, symbol):
        return 49_950.0

    async def fetch_top_of_book(self, symbol):
        return 49_900.0, 50_000.0

    async def normalize(self, symbol, amount, price):
        return float(amount), float(price)

    def market_limits(self, symbol):
        return 0.0001, 1.0

    async def fetch_free_balance(self, currency):
        return 1.0

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_shadow_submission_records_reference_price(tmp_path):
    ledger = LiveLedger(tmp_path / "live.db")
    await ledger.initialize()
    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=lambda spec, sandbox, creds: PassiveGateway(),
    )
    # shadow is exempt from the reconciliation gate
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "shadow"
    rows = await ledger.get_shadow_rows()
    assert rows[0]["reference_price"] == pytest.approx(49_950.0)


@pytest.mark.asyncio
async def test_gate_refusal_is_recorded(tmp_path):
    ledger = LiveLedger(tmp_path / "live.db")
    await ledger.initialize()
    service = ExchangeExecutionService(
        settings=_settings(enabled=()),
        ledger=ledger,
        gateway_factory=lambda spec, sandbox, creds: PassiveGateway(),
    )
    result = await service.submit_signal("binance", "sig-9", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    counts = await ledger.refusal_counts("binance")
    assert counts.get("exchange_not_enabled") == 1


@pytest.mark.asyncio
async def test_unknown_exchange_is_not_recorded(tmp_path):
    ledger = LiveLedger(tmp_path / "live.db")
    await ledger.initialize()
    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=lambda spec, sandbox, creds: PassiveGateway(),
    )
    result = await service.submit_signal("nope", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.reason == "unknown_exchange"
    assert await ledger.refusal_counts() == {}


@pytest.mark.asyncio
async def test_report_uses_refusals_and_reference_prices(tmp_path):
    from scripts.exchange_shadow_report import build_report, soak_exit_criteria

    ledger = LiveLedger(tmp_path / "live.db")
    await ledger.initialize()
    intent = OrderIntent(
        exchange_id="binance",
        signal_id="sig-1",
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_400.0,
        client_order_id="cid-1",
        sandbox=False,
    )
    await ledger.append_pending(intent, "shadow", "shadow", reference_price=50_000.0)
    await ledger.record_refusal("binance", "sig-2", "exchange_not_ready")
    summary = await build_report(ledger)
    assert summary["count"] == 1
    assert summary["deviation_samples"] == 1
    assert summary["max_deviation_pct"] == pytest.approx(0.8, abs=0.01)
    assert summary["reasons"]["exchange_not_ready"] == 1
    assert soak_exit_criteria(summary, 2.0)["no_exchange_not_ready"] is False
