from datetime import UTC, datetime, timedelta

import pytest

from domain.exchange_types import (
    OPEN,
    SUBMITTED,
    UNKNOWN,
    OrderIntent,
)
from trading.exchanges.registry import ExchangeSpec
from trading.live_ledger import LiveLedger
from trading.reconciliation import reconcile_once


def _intent(signal_id="sig-1", exchange_id="binance", client_order_id="cid-1"):
    return OrderIntent(
        exchange_id=exchange_id,
        signal_id=signal_id,
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_000.0,
        client_order_id=client_order_id,
        sandbox=True,
    )


class FailingGateway:
    def __init__(self, error, exchange_id="binance"):
        self.error = error
        self.exchange_id = exchange_id
        self.calls = 0
        self.spec = ExchangeSpec(
            exchange_id=exchange_id,
            display_name=exchange_id.title(),
            ccxt_id=exchange_id,
            access_scope="general",
            status="ready",
            spot_supported=True,
            needs_passphrase=False,
            secret_encoding="plain",
            sandbox_expected=None,
            permission_endpoint=None,
            client_id_supported=True,
        )

    async def fetch_order_by_exchange_id(self, symbol, exchange_order_id):
        self.calls += 1
        raise self.error

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        self.calls += 1
        raise self.error

    def error_text(self, exc):
        return str(exc)


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


@pytest.mark.asyncio
async def test_a_read_failure_before_the_threshold_keeps_the_status(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    gateway = FailingGateway(RuntimeError("network down"))
    now = datetime.now(UTC)

    changed = await reconcile_once(
        ledger,
        {"binance": gateway},
        120.0,
        now_utc=now,
        notify=_recorder(),
    )

    assert changed == []
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == SUBMITTED


@pytest.mark.asyncio
async def test_a_persistent_read_failure_escalates_to_unknown_after_the_threshold(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    gateway = FailingGateway(RuntimeError("network down"))
    now = datetime.now(UTC)
    notices = _recorder()

    changed = await reconcile_once(
        ledger, {"binance": gateway}, 120.0, now_utc=now + timedelta(hours=2), notify=notices
    )

    assert changed == ["cid-1"]
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == UNKNOWN
    assert len(notices.notices) == 1
    assert "unknown" in notices.notices[0]


@pytest.mark.asyncio
async def test_the_unknown_notice_is_not_repeated(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    gateway = FailingGateway(RuntimeError("network down"))
    late = datetime.now(UTC) + timedelta(hours=2)
    notices = _recorder()

    await reconcile_once(ledger, {"binance": gateway}, 120.0, now_utc=late, notify=notices)
    await reconcile_once(ledger, {"binance": gateway}, 120.0, now_utc=late, notify=notices)
    await reconcile_once(ledger, {"binance": gateway}, 120.0, now_utc=late, notify=notices)

    assert len(notices.notices) == 1


@pytest.mark.asyncio
async def test_a_read_failure_does_not_change_an_open_row(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", OPEN, "sent")
    gateway = FailingGateway(RuntimeError("network down"))
    late = datetime.now(UTC) + timedelta(hours=2)

    await reconcile_once(ledger, {"binance": gateway}, 120.0, now_utc=late, notify=_recorder())

    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == OPEN


@pytest.mark.asyncio
async def test_a_pending_submit_read_failure_escalates_to_unknown(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    gateway = FailingGateway(RuntimeError("network down"))
    late = datetime.now(UTC) + timedelta(hours=2)

    changed = await reconcile_once(
        ledger, {"binance": gateway}, 120.0, now_utc=late, notify=_recorder()
    )

    assert changed == ["cid-1"]
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == UNKNOWN


@pytest.mark.asyncio
async def test_the_read_failure_log_does_not_leak_the_secret(ledger):
    from loguru import logger as loguru_logger

    secret = "SECRET_KEY_VALUE_123"
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    gateway = _SanitizingFailingGateway(RuntimeError(f"auth failed for {secret}"), secret)
    late = datetime.now(UTC) + timedelta(hours=2)

    records: list[str] = []
    handler_id = loguru_logger.add(
        lambda m: records.append(m.record["message"]), format="{message}", level="DEBUG"
    )
    try:
        await reconcile_once(ledger, {"binance": gateway}, 120.0, now_utc=late, notify=_recorder())
    finally:
        loguru_logger.remove(handler_id)

    joined = "\n".join(records)
    assert secret not in joined


class _SanitizingFailingGateway(FailingGateway):
    def __init__(self, error, secret):
        super().__init__(error)
        self._secrets = [secret]

    def error_text(self, exc):
        return str(exc).replace(self._secrets[0], "***")


class _Recorder:
    def __init__(self):
        self.notices: list[str] = []

    async def __call__(self, text):
        self.notices.append(text)


def _recorder() -> _Recorder:
    return _Recorder()
