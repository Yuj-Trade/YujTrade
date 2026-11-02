import pytest

from domain.exchange_types import REJECTED, SUBMITTED, PlacementResult
from trading.exchanges.confirmation import check_confirmation, issue_confirmation
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
    def __init__(self):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec("binance")
        self.exchange_id = "binance"
        self.placed = 0

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

    async def close(self):
        return None


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

    service = ExchangeExecutionService(
        settings=_live_settings(),
        ledger=ledger,
        gateway_factory=factory,
        permission_check=permission_check,
        review_ok=True,
        execution_dry_run=False,
    )
    service.reconciled_venues = {"binance"}
    return service


@pytest.mark.asyncio
async def test_a_duplicate_signal_does_not_consume_the_code(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)

    first_code = await service.request_confirmation("binance", "sig-1")
    first = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=first_code
    )
    assert first.ok is True
    assert gateway.placed == 1

    second_code = await service.request_confirmation("binance", "sig-1")
    duplicate = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=second_code
    )

    assert duplicate.ok is False
    assert duplicate.reason == "duplicate_signal"
    assert gateway.placed == 1

    still_valid, reason = await check_confirmation(ledger, second_code, "binance", "sig-1")
    assert still_valid is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_a_new_signal_consumes_the_code_once(ledger):
    gateway = CountingGateway()
    service = _service(ledger, gateway)

    code = await service.request_confirmation("binance", "sig-1")
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )

    assert result.ok is True
    assert result.status == SUBMITTED
    assert gateway.placed == 1

    reused, reason = await check_confirmation(ledger, code, "binance", "sig-1")
    assert reused is False
    assert reason == "confirmation_already_used"


@pytest.mark.asyncio
async def test_a_lost_consume_race_marks_the_row_rejected(ledger, monkeypatch):
    gateway = CountingGateway()
    service = _service(ledger, gateway)

    async def lose_race(_ledger, _code, _exchange_id, _signal_id):
        return False, "confirmation_already_used"

    import trading.exchanges.execution_service as module

    monkeypatch.setattr(module, "consume_confirmation", lose_race)

    code = await issue_confirmation(ledger, "binance", "sig-1")
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )

    assert result.ok is False
    assert result.reason == "confirmation_already_used"
    assert gateway.placed == 0

    row = await ledger.get_row(result.client_order_id, "binance")
    assert row is not None
    assert row["status"] == REJECTED
