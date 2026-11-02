import pytest

from domain.exchange_types import CANCELED, FILLED, SUBMITTED, OrderIntent, OrderSnapshot
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


def _intent(client_order_id="cid-1"):
    return OrderIntent(
        exchange_id="binance",
        signal_id="sig-" + client_order_id,
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_000.0,
        client_order_id=client_order_id,
        sandbox=True,
    )


class CancelGateway:
    def __init__(self, snapshot=None, cancel_result=(True, "canceled"), raises=None):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec("binance")
        self.exchange_id = "binance"
        self.snapshot = snapshot
        self.cancel_result = cancel_result
        self.raises = raises
        self.cancel_calls: list[tuple[str, str]] = []
        self.closed = 0

    async def cancel_order(self, symbol, exchange_order_id):
        self.cancel_calls.append((symbol, exchange_order_id))
        if self.raises is not None:
            raise self.raises
        return self.cancel_result

    async def fetch_order_by_exchange_id(self, symbol, exchange_order_id):
        return self.snapshot

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        return self.snapshot

    async def close(self):
        self.closed += 1


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


def _service(ledger, gateway):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    async def permission_check(spec):
        return True

    def factory(spec, sandbox, creds):
        return gateway

    import trading.exchanges.execution_service as module

    module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())
    module.load_exchange_credentials = lambda spec, sandbox: credentials

    return ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=factory,
        permission_check=permission_check,
        review_ok=True,
    )


async def _submitted_row(ledger, client_order_id="cid-1"):
    await ledger.append_pending(_intent(client_order_id), "sandbox")
    await ledger.set_status(client_order_id, "binance", SUBMITTED, "sent")
    await ledger.set_exchange_order_id(client_order_id, "binance", "ex-1")


@pytest.mark.asyncio
async def test_a_submitted_order_is_cancelled_and_refreshed(ledger):
    await _submitted_row(ledger)
    snapshot = OrderSnapshot("ex-1", "cid-1", CANCELED, 0.0, 0.0, 0.0, "")
    gateway = CancelGateway(snapshot=snapshot)
    service = _service(ledger, gateway)

    result = await service.cancel("binance", "cid-1")

    assert result["ok"] is True
    assert gateway.cancel_calls == [("BTC/USDT", "ex-1")]
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == CANCELED
    assert result["status"] == CANCELED
    assert gateway.closed == 1


@pytest.mark.asyncio
async def test_a_terminal_order_is_not_cancelled(ledger):
    await _submitted_row(ledger)
    await ledger.update_from_snapshot(
        "cid-1", "binance", OrderSnapshot("ex-1", "cid-1", FILLED, 0.0005, 50_000.0, 0.0, "")
    )
    gateway = CancelGateway()
    service = _service(ledger, gateway)

    result = await service.cancel("binance", "cid-1")

    assert result["ok"] is False
    assert result["reason"] == "already_terminal"
    assert gateway.cancel_calls == []


@pytest.mark.asyncio
async def test_a_shadow_row_is_not_cancelled_on_a_venue(ledger):
    await ledger.append_pending(_intent(), "shadow", "shadow")
    gateway = CancelGateway()
    service = _service(ledger, gateway)

    result = await service.cancel("binance", "cid-1")

    assert result["ok"] is False
    assert result["reason"] in {"already_terminal", "shadow_has_no_venue_order"}
    assert gateway.cancel_calls == []


@pytest.mark.asyncio
async def test_a_row_without_a_venue_id_is_refused(ledger):
    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", SUBMITTED, "sent")
    gateway = CancelGateway()
    service = _service(ledger, gateway)

    result = await service.cancel("binance", "cid-1")

    assert result["ok"] is False
    assert result["reason"] == "no_venue_order_id"
    assert gateway.cancel_calls == []


@pytest.mark.asyncio
async def test_an_unknown_order_is_refused(ledger):
    gateway = CancelGateway()
    service = _service(ledger, gateway)

    result = await service.cancel("binance", "missing")

    assert result["ok"] is False
    assert result["reason"] == "unknown_order"


@pytest.mark.asyncio
async def test_cancel_is_allowed_while_halted(ledger):
    await _submitted_row(ledger)
    snapshot = OrderSnapshot("ex-1", "cid-1", CANCELED, 0.0, 0.0, 0.0, "")
    gateway = CancelGateway(snapshot=snapshot)
    service = _service(ledger, gateway)
    await service.halt()

    result = await service.cancel("binance", "cid-1")

    assert result["ok"] is True
    assert len(gateway.cancel_calls) == 1


@pytest.mark.asyncio
async def test_order_not_found_leaves_the_row_unchanged(ledger):
    await _submitted_row(ledger)
    gateway = CancelGateway(cancel_result=(False, "order_not_found"))
    service = _service(ledger, gateway)

    result = await service.cancel("binance", "cid-1")

    assert result["ok"] is False
    assert result["reason"] == "order_not_found"
    row = await ledger.get_row("cid-1", "binance")
    assert row["status"] == SUBMITTED


@pytest.mark.asyncio
async def test_ccxt_cancel_order_maps_order_not_found():
    import ccxt.async_support as ccxt_async

    from trading.exchanges.ccxt_gateway import CcxtGateway
    from trading.exchanges.registry import get_spec

    gateway = CcxtGateway(spec=get_spec("kraken"), sandbox=False, credentials=None)

    class _Client:
        async def cancel_order(self, order_id, symbol):
            raise ccxt_async.OrderNotFound("gone")

    gateway.client = _Client()

    ok, reason = await gateway.cancel_order("BTC/USDT", "ex-1")

    assert ok is False
    assert reason == "order_not_found"


@pytest.mark.asyncio
async def test_ccxt_cancel_order_maps_exchange_error_to_sanitized_text():
    import ccxt.async_support as ccxt_async

    from trading.exchanges.ccxt_gateway import CcxtGateway
    from trading.exchanges.registry import get_spec

    gateway = CcxtGateway(spec=get_spec("kraken"), sandbox=False, credentials=None)

    class _Client:
        async def cancel_order(self, order_id, symbol):
            raise ccxt_async.ExchangeError("bad request")

    gateway.client = _Client()

    ok, reason = await gateway.cancel_order("BTC/USDT", "ex-1")

    assert ok is False
    assert "bad request" in reason


@pytest.mark.asyncio
async def test_cancel_order_is_only_wired_into_cancel_and_gateway():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[3]
    production = [root / "trading" / "exchanges", root / "application"]
    call_sites = []
    for base in production:
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if re.search(r"\.cancel_order\(", line):
                    call_sites.append((path.relative_to(root).as_posix(), line_number))
    allowed = {
        "trading/exchanges/ccxt_gateway.py",
        "trading/exchanges/execution_service.py",
    }
    for relative, _line in call_sites:
        assert relative in allowed, relative
