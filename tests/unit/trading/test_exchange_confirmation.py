from datetime import UTC, datetime, timedelta

import pytest

from domain.exchange_types import SUBMITTED
from trading.exchanges.confirmation import consume_confirmation, issue_confirmation
from trading.exchanges.execution_service import ExchangeExecutionService
from trading.exchanges.gate_inputs import ExchangeSettings
from trading.live_ledger import LiveLedger


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


def _live_settings() -> ExchangeSettings:
    return ExchangeSettings(
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


def _sandbox_settings() -> ExchangeSettings:
    base = _live_settings()
    return ExchangeSettings(
        enabled=base.enabled,
        access_profile=base.access_profile,
        sandbox=True,
        shadow_mode=False,
        live_enabled=False,
        live_review_id="",
        attested_keys=(),
        symbol_allowlist=base.symbol_allowlist,
        max_order_notional=base.max_order_notional,
        max_daily_notional=base.max_daily_notional,
        max_deviation_pct=base.max_deviation_pct,
        max_spread_pct=base.max_spread_pct,
        ledger_path=base.ledger_path,
        reconcile_interval_seconds=base.reconcile_interval_seconds,
        unknown_after_seconds=base.unknown_after_seconds,
        request_timeout_ms=base.request_timeout_ms,
    )


class CountingGateway:
    def __init__(self):
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
        from domain.exchange_types import PlacementResult

        self.placed += 1
        return PlacementResult(accepted=True, exchange_order_id="ex-1")

    async def close(self):
        return None


def _service(ledger, settings, gateway, dry_run=False):
    from trading.exchanges.credentials import ExchangeCredentials

    credentials = ExchangeCredentials(api_key="k", api_secret="s")

    def factory(spec, sandbox, creds):
        return gateway

    import trading.exchanges.execution_service as module

    module.credentials_usable = lambda spec, sandbox: (True, credentials.as_list())

    async def permission_check(spec):
        return True

    return ExchangeExecutionService(
        settings=settings,
        ledger=ledger,
        gateway_factory=factory,
        execution_dry_run=dry_run,
        permission_check=permission_check,
    )


@pytest.mark.asyncio
async def test_confirmation_roundtrip(ledger):
    code = await issue_confirmation(ledger, "binance", "sig-1")
    ok, reason = await consume_confirmation(ledger, code, "binance", "sig-1")
    assert (ok, reason) == (True, "ok")


@pytest.mark.asyncio
async def test_wrong_code_is_refused(ledger):
    await issue_confirmation(ledger, "binance", "sig-1")
    ok, reason = await consume_confirmation(ledger, "DEADBEEF", "binance", "sig-1")
    assert (ok, reason) == (False, "confirmation_unknown")


@pytest.mark.asyncio
async def test_expired_code_is_refused(ledger):
    code = await issue_confirmation(ledger, "binance", "sig-1", ttl_seconds=1.0)
    later = datetime.now(UTC) + timedelta(seconds=5)
    ok, reason = await consume_confirmation(ledger, code, "binance", "sig-1", now=later)
    assert (ok, reason) == (False, "confirmation_expired")


@pytest.mark.asyncio
async def test_code_cannot_be_reused(ledger):
    code = await issue_confirmation(ledger, "binance", "sig-1")
    first = await consume_confirmation(ledger, code, "binance", "sig-1")
    second = await consume_confirmation(ledger, code, "binance", "sig-1")
    assert first == (True, "ok")
    assert second == (False, "confirmation_already_used")


@pytest.mark.asyncio
async def test_code_must_match_signal(ledger):
    code = await issue_confirmation(ledger, "binance", "sig-1")
    ok, reason = await consume_confirmation(ledger, code, "binance", "sig-2")
    assert (ok, reason) == (False, "confirmation_mismatch")


@pytest.mark.asyncio
async def test_live_submission_needs_a_code(ledger):
    gateway = CountingGateway()
    service = _service(ledger, _live_settings(), gateway)
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=""
    )
    assert result.ok is False
    assert result.reason == "confirmation_missing"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_live_submission_with_valid_code_places_order(ledger):
    gateway = CountingGateway()
    service = _service(ledger, _live_settings(), gateway)
    code = await issue_confirmation(ledger, "binance", "sig-1")
    result = await service.submit_signal(
        "binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0, confirmation_code=code
    )
    assert result.ok is True
    assert result.mode == "live"
    assert result.status == SUBMITTED
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_sandbox_needs_no_code(ledger):
    gateway = CountingGateway()
    service = _service(ledger, _sandbox_settings(), gateway)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "sandbox"
    assert gateway.placed == 1


@pytest.mark.asyncio
async def test_shadow_needs_no_code(ledger):
    gateway = CountingGateway()
    settings = _sandbox_settings()
    shadow = ExchangeSettings(
        enabled=settings.enabled,
        access_profile=settings.access_profile,
        sandbox=False,
        shadow_mode=True,
        live_enabled=True,
        live_review_id="ADR-0011",
        attested_keys=("binance",),
        symbol_allowlist=settings.symbol_allowlist,
        max_order_notional=settings.max_order_notional,
        max_daily_notional=settings.max_daily_notional,
        max_deviation_pct=settings.max_deviation_pct,
        max_spread_pct=settings.max_spread_pct,
        ledger_path=settings.ledger_path,
        reconcile_interval_seconds=settings.reconcile_interval_seconds,
        unknown_after_seconds=settings.unknown_after_seconds,
        request_timeout_ms=settings.request_timeout_ms,
    )
    service = _service(ledger, shadow, gateway)
    result = await service.submit_signal("binance", "sig-1", "BTC/USDT", "buy", 0.0005, 50_000.0)
    assert result.ok is True
    assert result.mode == "shadow"
    assert gateway.placed == 0


@pytest.mark.asyncio
async def test_default_configuration_never_submits_live(ledger):
    from config.settings import ConfigManager

    defaults = ConfigManager.DEFAULT_CONFIG
    assert defaults["exchange_live_enabled"] is False
    assert defaults["exchange_sandbox"] is True
    assert defaults["exchange_shadow_mode"] is True
    assert defaults["execution_dry_run"] is True
    assert defaults["exchange_enabled"] == []


def test_every_incomplete_live_condition_refuses_live():
    from application.exchange_policy import submission_mode
    from trading.exchanges.gate_inputs import build_gate_input
    from trading.exchanges.registry import get_spec

    spec = get_spec("binance")
    complete = _live_settings()
    base = build_gate_input(
        spec=spec,
        settings=complete,
        creds_ok=True,
        permissions_ok=True,
        halted=False,
        sandbox_mode_flag=False,
        execution_dry_run=False,
        review_ok=True,
    )
    assert submission_mode(base) == ("live", "ok")
    variations = [
        dict(creds_ok=False),
        dict(permissions_ok=False),
        dict(execution_dry_run=True),
    ]
    for overrides in variations:
        params = dict(
            spec=spec,
            settings=complete,
            creds_ok=True,
            permissions_ok=True,
            halted=False,
            sandbox_mode_flag=False,
            execution_dry_run=False,
            review_ok=True,
        )
        params.update(overrides)
        mode, _ = submission_mode(build_gate_input(**params))
        assert mode != "live", overrides
    for field_name, value in (
        ("live_enabled", False),
        ("attested_keys", ()),
    ):
        settings = (
            ExchangeSettings(**{**complete.__dict__, field_name: value})
            if field_name != "live_enabled"
            else ExchangeSettings(**{**complete.__dict__, "live_enabled": False})
        )
        gate = build_gate_input(
            spec=spec,
            settings=settings,
            creds_ok=True,
            permissions_ok=True,
            halted=False,
            sandbox_mode_flag=False,
            execution_dry_run=False,
            review_ok=True,
        )
        mode, _ = submission_mode(gate)
        assert mode != "live"
    no_review = build_gate_input(
        spec=spec,
        settings=complete,
        creds_ok=True,
        permissions_ok=True,
        halted=False,
        sandbox_mode_flag=False,
        execution_dry_run=False,
        review_ok=False,
    )
    assert submission_mode(no_review)[0] != "live"


def test_review_is_accepted_reads_adr_status(tmp_path):
    from trading.exchanges.gate_inputs import review_is_accepted

    accepted = tmp_path / "ADR-0011-exchange-connectivity.md"
    accepted.write_text("# ADR-0011\n\nStatus: accepted\n", encoding="utf-8")
    proposed = tmp_path / "ADR-0012-exchange-access-profiles.md"
    proposed.write_text("# ADR-0012\n\nStatus: proposed\n", encoding="utf-8")
    assert review_is_accepted("ADR-0011", tmp_path) is True
    assert review_is_accepted("ADR-0012", tmp_path) is False
    assert review_is_accepted("ADR-9999", tmp_path) is False
    assert review_is_accepted("not-an-adr", tmp_path) is False
    assert review_is_accepted("", tmp_path) is False


def test_rejected_review_blocks_live():
    from application.exchange_policy import submission_mode
    from trading.exchanges.gate_inputs import build_gate_input
    from trading.exchanges.registry import get_spec

    spec = get_spec("binance")
    settings = ExchangeSettings(**{**_live_settings().__dict__, "live_review_id": "ADR-0012"})
    gate = build_gate_input(
        spec=spec,
        settings=settings,
        creds_ok=True,
        permissions_ok=True,
        halted=False,
        sandbox_mode_flag=False,
        execution_dry_run=False,
        review_ok=False,
    )
    mode, reason = submission_mode(gate)
    assert mode is None
    assert reason == "review_not_accepted"
