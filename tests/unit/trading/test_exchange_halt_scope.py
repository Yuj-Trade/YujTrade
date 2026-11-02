import pytest

from domain.exchange_types import PlacementResult
from trading.exchanges.execution_service import ExchangeExecutionService
from trading.exchanges.gate_inputs import ExchangeSettings
from trading.live_ledger import LiveLedger


def _settings(**overrides) -> ExchangeSettings:
    base = dict(
        enabled=("binance", "kraken"),
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


class VenueFakeGateway:
    def __init__(self, exchange_id):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec(exchange_id)
        self.exchange_id = exchange_id
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

    async def fetch_order_by_exchange_id(self, symbol, exchange_order_id):
        return None

    async def fetch_order_by_client_id(self, symbol, client_order_id):
        return None

    def error_text(self, exc):
        return str(exc)

    async def close(self):
        return None


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


def _service(ledger, gateways):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    async def permission_check(spec):
        return True

    def factory(spec, sandbox, creds):
        return gateways[spec.exchange_id]

    import trading.exchanges.execution_service as execution_module

    execution_module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())

    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=factory,
        permission_check=permission_check,
        review_ok=True,
    )
    service.reconciled_venues = {"binance", "kraken"}
    return service


@pytest.mark.asyncio
async def test_a_venue_halt_only_blocks_that_venue(ledger):
    gateways = {"binance": VenueFakeGateway("binance"), "kraken": VenueFakeGateway("kraken")}
    service = _service(ledger, gateways)

    await service.halt(exchange_id="binance")

    binance = await service.submit_signal("binance", "sig-b", "BTC/USDT", "buy", 0.0005, 50_000.0)
    kraken = await service.submit_signal("kraken", "sig-k", "BTC/USDT", "buy", 0.0005, 50_000.0)

    assert binance.ok is False
    assert "halted" in binance.reason
    assert kraken.ok is True
    assert gateways["kraken"].placed == 1
    assert gateways["binance"].placed == 0


@pytest.mark.asyncio
async def test_a_global_halt_blocks_every_venue(ledger):
    gateways = {"binance": VenueFakeGateway("binance"), "kraken": VenueFakeGateway("kraken")}
    service = _service(ledger, gateways)

    await service.halt()

    binance = await service.submit_signal("binance", "sig-b", "BTC/USDT", "buy", 0.0005, 50_000.0)
    kraken = await service.submit_signal("kraken", "sig-k", "BTC/USDT", "buy", 0.0005, 50_000.0)

    assert binance.ok is False
    assert kraken.ok is False
    assert gateways["binance"].placed == 0
    assert gateways["kraken"].placed == 0


@pytest.mark.asyncio
async def test_resuming_a_venue_reenables_only_that_venue(ledger):
    gateways = {"binance": VenueFakeGateway("binance"), "kraken": VenueFakeGateway("kraken")}
    service = _service(ledger, gateways)
    await service.halt(exchange_id="binance")

    await service.resume(exchange_id="binance")

    binance = await service.submit_signal("binance", "sig-b", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert binance.ok is True
    assert gateways["binance"].placed == 1


@pytest.mark.asyncio
async def test_resuming_a_venue_does_not_lift_a_global_halt(ledger):
    gateways = {"binance": VenueFakeGateway("binance"), "kraken": VenueFakeGateway("kraken")}
    service = _service(ledger, gateways)
    await service.halt()
    await service.halt(exchange_id="binance")

    await service.resume(exchange_id="binance")

    state = await service.halt_state(exchange_id="binance")
    assert state["global"] is True
    assert state["venue"] is False
    assert state["halted"] is True
    binance = await service.submit_signal("binance", "sig-b", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert binance.ok is False
