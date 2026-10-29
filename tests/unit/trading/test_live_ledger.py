from datetime import UTC, datetime

import pytest

from domain.exchange_types import (
    FILLED,
    OPEN,
    PENDING_SUBMIT,
    SHADOW,
    SUBMITTED,
    UNKNOWN,
    OrderIntent,
    OrderSnapshot,
)
from trading.live_ledger import LiveLedger
from trading.reconciliation import reconcile_once


def _intent(signal_id="sig-1", exchange_id="binance", client_order_id="cid-1", side="buy"):
    return OrderIntent(
        exchange_id=exchange_id,
        signal_id=signal_id,
        symbol="BTC/USDT",
        side=side,
        amount=0.0005,
        price=50_000.0,
        client_order_id=client_order_id,
        sandbox=True,
    )


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


@pytest.mark.asyncio
async def test_append_pending_and_read_back(ledger):
    assert await ledger.append_pending(_intent(), "sandbox") is True
    row = await ledger.get_row("cid-1", "binance")
    assert row is not None
    assert row["status"] == PENDING_SUBMIT
    assert row["mode"] == "sandbox"


@pytest.mark.asyncio
async def test_duplicate_signal_id_is_refused(ledger):
    assert await ledger.append_pending(_intent(), "sandbox") is True
    assert await ledger.append_pending(_intent(client_order_id="cid-2"), "sandbox") is False


@pytest.mark.asyncio
async def test_duplicate_client_order_id_is_refused(ledger):
    assert await ledger.append_pending(_intent(), "sandbox") is True
    assert await ledger.append_pending(_intent(signal_id="sig-2"), "sandbox") is False


@pytest.mark.asyncio
async def test_shadow_row_status(ledger):
    assert await ledger.append_pending(_intent(), "shadow") is True
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == SHADOW


@pytest.mark.asyncio
async def test_update_from_snapshot(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    snapshot = OrderSnapshot(
        exchange_order_id="ex-1",
        client_order_id="cid-1",
        status=FILLED,
        filled=0.0005,
        average_price=50_100.0,
        fee_cost=0.02,
        fee_currency="USDT",
    )
    assert await ledger.update_from_snapshot("cid-1", "binance", snapshot) is True
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == FILLED
    assert row["exchange_order_id"] == "ex-1"
    assert row["filled"] == pytest.approx(0.0005)
    assert row["fee_cost"] == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_terminal_status_is_locked(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    snapshot = OrderSnapshot("ex-1", "cid-1", FILLED, 0.0005, 50_000.0, 0.0, "")
    await ledger.update_from_snapshot("cid-1", "binance", snapshot)
    assert await ledger.set_status("cid-1", "binance", OPEN) is False
    second = OrderSnapshot("ex-1", "cid-1", OPEN, 0.0, 0.0, 0.0, "")
    assert await ledger.update_from_snapshot("cid-1", "binance", second) is False
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == FILLED


@pytest.mark.asyncio
async def test_set_status_updates_reason(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    assert await ledger.set_status("cid-1", "binance", SUBMITTED, "sent") is True
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == SUBMITTED
    assert row["reason"] == "sent"


@pytest.mark.asyncio
async def test_get_non_terminal_filters(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.append_pending(_intent(signal_id="sig-2", client_order_id="cid-2"), "sandbox")
    await ledger.set_status("cid-2", "binance", FILLED)
    rows = await ledger.get_non_terminal()
    assert [row["client_order_id"] for row in rows] == ["cid-1"]
    assert await ledger.get_non_terminal("kraken") == []


@pytest.mark.asyncio
async def test_daily_notional_sums_sandbox_and_live(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.append_pending(_intent(signal_id="s2", client_order_id="c2"), "live")
    await ledger.append_pending(_intent(signal_id="s3", client_order_id="c3"), "shadow")
    await ledger.append_pending(_intent(signal_id="s4", client_order_id="c4"), "sandbox")
    await ledger.set_status("c4", "binance", "rejected")
    today = datetime.now(UTC).date()
    expected = 0.0005 * 50_000.0 * 2
    assert await ledger.daily_notional("binance", today) == pytest.approx(expected)


@pytest.mark.asyncio
async def test_daily_notional_other_day_is_zero(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    assert await ledger.daily_notional("binance", "1999-01-01") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_control_roundtrip(ledger):
    assert await ledger.get_control("halted", "0") == "0"
    await ledger.set_control("halted", "1")
    assert await ledger.get_control("halted", "0") == "1"
    await ledger.set_control("halted", "0")
    assert await ledger.get_control("halted", "0") == "0"


class FakeGateway:
    def __init__(self, snapshot=None, error=None, exchange_id="binance"):
        self.snapshot = snapshot
        self.error = error
        self.exchange_id = exchange_id
        self.calls = 0

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.snapshot

    def error_text(self, exc):
        return str(exc)


@pytest.mark.asyncio
async def test_restart_resolves_submitted_row_once(tmp_path):
    path = tmp_path / "live.db"
    first = LiveLedger(path)
    await first.initialize()
    await first.append_pending(_intent(), "sandbox")
    await first.set_status("cid-1", "binance", SUBMITTED, "sent")
    await first.close()

    second = LiveLedger(path)
    await second.initialize()
    snapshot = OrderSnapshot("ex-1", "cid-1", FILLED, 0.0005, 50_000.0, 0.01, "USDT")
    gateway = FakeGateway(snapshot=snapshot)
    changed = await reconcile_once(second, {"binance": gateway}, 120.0)
    assert changed == ["cid-1"]
    rows = await second.get_non_terminal()
    assert rows == []
    row = await second.get_row("cid-1", "binance")
    assert row["status"] == FILLED
    again = await reconcile_once(second, {"binance": gateway}, 120.0)
    assert again == []


@pytest.mark.asyncio
async def test_unknown_after_threshold(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    notices = []

    async def notify(text):
        notices.append(text)

    gateway = FakeGateway(snapshot=None)
    changed = await reconcile_once(
        ledger, {"binance": gateway}, 0.0, now_utc=datetime.now(UTC), notify=notify
    )
    assert changed == ["cid-1"]
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == UNKNOWN
    assert notices and "unknown" in notices[0]


@pytest.mark.asyncio
async def test_open_snapshot_does_not_become_unknown(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    snapshot = OrderSnapshot("ex-1", "cid-1", OPEN, 0.0, 0.0, 0.0, "")
    gateway = FakeGateway(snapshot=snapshot)
    await reconcile_once(ledger, {"binance": gateway}, 0.0)
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == OPEN


@pytest.mark.asyncio
async def test_missing_gateway_is_skipped(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    changed = await reconcile_once(ledger, {}, 60.0)
    assert changed == []
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == PENDING_SUBMIT


@pytest.mark.asyncio
async def test_gateway_error_is_skipped(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    gateway = FakeGateway(error=RuntimeError("network down"))
    changed = await reconcile_once(ledger, {"binance": gateway}, 0.0)
    assert changed == []
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == PENDING_SUBMIT


@pytest.mark.asyncio
async def test_reconcile_never_creates_a_second_row(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    gateway = FakeGateway(
        snapshot=OrderSnapshot("ex-1", "cid-1", FILLED, 0.0005, 50_000.0, 0.0, "")
    )
    await reconcile_once(ledger, {"binance": gateway}, 60.0)
    await reconcile_once(ledger, {"binance": gateway}, 60.0)
    assert await ledger.append_pending(_intent(), "sandbox") is False
