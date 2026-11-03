import pytest

from domain.exchange_types import PlacementResult
from trading.exchanges.execution_service import ExchangeExecutionService
from trading.exchanges.gate_inputs import ExchangeSettings
from trading.live_ledger import LiveLedger


@pytest.fixture(autouse=True)
def _restore_module_patches():
    import trading.exchanges.credentials as credentials_module
    import trading.exchanges.execution_service as execution_module

    original_loader = credentials_module.load_exchange_credentials
    original_usable = execution_module.credentials_usable
    try:
        yield
    finally:
        credentials_module.load_exchange_credentials = original_loader
        execution_module.credentials_usable = original_usable


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


def _service(ledger, gateways, missing_credentials=()):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    async def permission_check(spec):
        return True

    import trading.exchanges.credentials as credentials_module
    import trading.exchanges.execution_service as execution_module

    def loader(spec, sandbox):
        return None if spec.exchange_id in missing_credentials else credentials

    def usable(spec, sandbox):
        if spec.exchange_id in missing_credentials:
            return False, []
        return True, credentials.as_list()

    credentials_module.load_exchange_credentials = loader
    execution_module.credentials_usable = usable

    def factory(spec, sandbox, creds):
        return gateways[spec.exchange_id]

    return ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=factory,
        notify=_no_notify,
        permission_check=permission_check,
        review_ok=True,
    )


async def _no_notify(_text):
    return None


@pytest.mark.asyncio
async def test_one_unhealthy_venue_does_not_block_the_healthy_one(ledger):
    gateways = {"binance": VenueFakeGateway("binance"), "kraken": VenueFakeGateway("kraken")}
    service = _service(ledger, gateways, missing_credentials=("binance",))

    await service.reconcile()

    assert "kraken" in service.reconciled_venues
    assert "binance" not in service.reconciled_venues

    kraken_result = await service.submit_signal(
        "kraken", "sig-k", "BTC/USDT", "buy", 0.0005, 50_000.0
    )
    assert kraken_result.ok is True
    assert gateways["kraken"].placed == 1

    binance_result = await service.submit_signal(
        "binance", "sig-b", "BTC/USDT", "buy", 0.0005, 50_000.0
    )
    assert binance_result.ok is False
    assert gateways["binance"].placed == 0


@pytest.mark.asyncio
async def test_an_unreconciled_venue_is_refused_by_name(ledger):
    from trading.exchanges.errors import ExchangeConfigError

    gateways = {"binance": VenueFakeGateway("binance"), "kraken": VenueFakeGateway("kraken")}

    def factory(spec, sandbox, creds):
        if spec.exchange_id == "binance":
            raise ExchangeConfigError("sandbox_not_supported")
        return gateways[spec.exchange_id]

    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    async def permission_check(spec):
        return True

    import trading.exchanges.credentials as credentials_module

    credentials_module.load_exchange_credentials = lambda spec, sandbox: credentials
    execution_module = __import__(
        "trading.exchanges.execution_service", fromlist=["credentials_usable"]
    )
    execution_module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())

    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=factory,
        notify=_no_notify,
        permission_check=permission_check,
        review_ok=True,
    )

    await service.reconcile()

    assert "kraken" in service.reconciled_venues
    assert "binance" not in service.reconciled_venues

    result = await service.submit_signal("binance", "sig-b", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is False
    assert result.reason == "reconciliation_pending:binance"
    assert gateways["binance"].placed == 0


@pytest.mark.asyncio
async def test_the_blocker_dict_is_bounded_across_failed_passes(ledger):
    from trading.exchanges.errors import ExchangeConfigError

    def failing_factory(spec, sandbox, creds):
        raise ExchangeConfigError("sandbox_not_supported")

    service = ExchangeExecutionService(
        settings=_settings(),
        ledger=ledger,
        gateway_factory=failing_factory,
    )

    for _ in range(3):
        await service.reconcile()

    assert len(service.reconcile_blockers) == 2
    assert set(service.reconcile_blockers) == {"binance", "kraken"}
    assert service.reconciled_venues == set()
