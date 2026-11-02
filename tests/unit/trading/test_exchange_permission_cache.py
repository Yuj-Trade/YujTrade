import pytest

from domain.exchange_types import PlacementResult
from trading.exchanges.execution_service import ExchangeExecutionService
from trading.exchanges.gate_inputs import ExchangeSettings, load_exchange_settings
from trading.live_ledger import LiveLedger


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _settings(**overrides) -> ExchangeSettings:
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
        permission_cache_seconds=600.0,
    )
    base.update(overrides)
    return ExchangeSettings(**base)


class CountingGateway:
    def __init__(self):
        from trading.exchanges.registry import get_spec

        self.spec = get_spec("binance")
        self.exchange_id = "binance"

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
        return PlacementResult(accepted=True, exchange_order_id="ex-1")

    async def close(self):
        return None


class CountingPermission:
    def __init__(self, verdict=True):
        self.calls = 0
        self.verdict = verdict

    async def __call__(self, spec):
        self.calls += 1
        return self.verdict


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


def _service(ledger, settings, permission, clock):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    import trading.exchanges.execution_service as module

    module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())

    service = ExchangeExecutionService(
        settings=settings,
        ledger=ledger,
        gateway_factory=lambda spec, sandbox, creds: CountingGateway(),
        permission_check=permission,
        review_ok=True,
        execution_dry_run=bool(settings.sandbox),
        clock=clock,
    )
    service.reconciled_venues = {"binance"}
    return service


@pytest.mark.asyncio
async def test_sandbox_skips_permission_check(ledger):
    permission = CountingPermission()
    clock = Clock()
    service = _service(ledger, _settings(sandbox=True), permission, clock)
    from trading.exchanges.registry import get_spec

    assert await service._permissions_ok(get_spec("binance"), use_sandbox=True) is True
    assert permission.calls == 0


@pytest.mark.asyncio
async def test_shadow_skips_permission_check(ledger):
    permission = CountingPermission()
    clock = Clock()
    settings = _settings(shadow_mode=True)
    service = _service(ledger, settings, permission, clock)
    from trading.exchanges.registry import get_spec

    await service._permissions_ok(get_spec("binance"), use_sandbox=False)
    assert permission.calls == 0


@pytest.mark.asyncio
async def test_live_permission_is_cached(ledger):
    permission = CountingPermission()
    clock = Clock()
    service = _service(ledger, _settings(), permission, clock)
    from trading.exchanges.registry import get_spec

    spec = get_spec("binance")
    assert await service._permissions_ok(spec, use_sandbox=False) is True
    assert await service._permissions_ok(spec, use_sandbox=False) is True
    assert permission.calls == 1
    clock.now += 601.0
    await service._permissions_ok(spec, use_sandbox=False)
    assert permission.calls == 2


@pytest.mark.asyncio
async def test_permission_failure_is_cached_too(ledger):
    permission = CountingPermission(verdict=False)
    clock = Clock()
    service = _service(ledger, _settings(), permission, clock)
    from trading.exchanges.registry import get_spec

    spec = get_spec("binance")
    assert await service._permissions_ok(spec, use_sandbox=False) is False
    assert await service._permissions_ok(spec, use_sandbox=False) is False
    assert permission.calls == 1


@pytest.mark.asyncio
async def test_permission_exception_is_false_and_cached(ledger):
    class Boom:
        def __init__(self):
            self.calls = 0

        async def __call__(self, spec):
            self.calls += 1
            raise RuntimeError("network down")

    boom = Boom()
    clock = Clock()
    service = _service(ledger, _settings(), boom, clock)
    from trading.exchanges.registry import get_spec

    spec = get_spec("binance")
    assert await service._permissions_ok(spec, use_sandbox=False) is False
    assert await service._permissions_ok(spec, use_sandbox=False) is False
    assert boom.calls == 1


def test_default_cache_seconds_is_configured():
    from config.settings import ConfigManager

    defaults = ConfigManager.DEFAULT_CONFIG
    assert defaults["exchange_permission_cache_seconds"] == 600
    settings = load_exchange_settings(ConfigManager())
    assert settings.permission_cache_seconds == 600.0


def test_no_live_defaults_changed():
    from config.settings import ConfigManager

    defaults = ConfigManager.DEFAULT_CONFIG
    assert defaults["exchange_live_enabled"] is False
    assert defaults["exchange_sandbox"] is True
    assert defaults["execution_dry_run"] is True
