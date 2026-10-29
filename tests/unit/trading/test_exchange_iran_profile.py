import pytest

from application.exchange_policy import PROFILE_GENERAL, PROFILE_IRAN, submission_mode
from trading.exchanges.errors import OurbitNotReady
from trading.exchanges.factory import build_gateway
from trading.exchanges.gate_inputs import ExchangeSettings, build_gate_input, profile_accepts
from trading.exchanges.registry import EXCHANGE_REGISTRY, get_spec, iran_only_exchange_ids


def _settings(profile: str, **overrides) -> ExchangeSettings:
    base = dict(
        enabled=tuple(spec.exchange_id for spec in EXCHANGE_REGISTRY),
        access_profile=profile,
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


def _mode_for(exchange_id: str, profile: str) -> tuple[str | None, str]:
    spec = get_spec(exchange_id)
    gate = build_gate_input(
        spec=spec,
        settings=_settings(profile),
        creds_ok=True,
        permissions_ok=True,
        halted=False,
        sandbox_mode_flag=True,
        execution_dry_run=True,
        review_ok=False,
    )
    return submission_mode(gate)


def test_iran_only_ids_are_lbank_and_ourbit():
    assert iran_only_exchange_ids() == ("lbank", "ourbit")


def test_iran_profile_accepts_iran_venues():
    for exchange_id in iran_only_exchange_ids():
        assert profile_accepts(PROFILE_IRAN, get_spec(exchange_id)) is True


def test_iran_profile_rejects_every_general_venue():
    for spec in EXCHANGE_REGISTRY:
        if spec.access_scope == "general":
            assert profile_accepts(PROFILE_IRAN, spec) is False, spec.exchange_id


def test_general_profile_rejects_iran_venues():
    for exchange_id in iran_only_exchange_ids():
        assert profile_accepts(PROFILE_GENERAL, get_spec(exchange_id)) is False


def test_scope_mismatch_is_reported_for_ready_venues():
    assert _mode_for("lbank", PROFILE_GENERAL) == (None, "scope_mismatch")
    assert _mode_for("binance", PROFILE_IRAN) == (None, "scope_mismatch")


def test_unknown_profile_rejects_everything():
    for spec in EXCHANGE_REGISTRY:
        assert profile_accepts("unknown-profile", spec) is False


def test_ourbit_factory_stays_not_ready():
    with pytest.raises(OurbitNotReady):
        build_gateway(get_spec("ourbit"), sandbox=False)


def test_ourbit_registry_status_is_pending():
    spec = get_spec("ourbit")
    assert spec.status == "pending_docs_verification"
    assert spec.ccxt_id is None


def test_lbank_is_ready_and_iran_only():
    spec = get_spec("lbank")
    assert spec.status == "ready"
    assert spec.ccxt_id == "lbank"
    assert spec.access_scope == "iran_users_only"


def test_lbank_permission_rule_blocks_live():
    from trading.exchanges.permissions import verify_key_permissions

    class FakeClient:
        def describe(self):
            return {
                "api": {
                    "spot": {"private": {"post": {"supplement/api_Restrictions": {"cost": 2.5}}}}
                }
            }

        async def request(self, path, section, method, params):
            return {}

    class FakeGateway:
        client = FakeClient()
        _secrets = []

    async def run():
        return await verify_key_permissions(FakeGateway(), get_spec("lbank"))

    import asyncio

    ok, reason = asyncio.run(run())
    assert (ok, reason) == (False, "lbank_rule_not_defined")


def test_deribit_is_not_spot_and_refused():
    spec = get_spec("deribit")
    assert spec.spot_supported is False
    gate = build_gate_input(
        spec=spec,
        settings=_settings(PROFILE_GENERAL),
        creds_ok=True,
        permissions_ok=True,
        halted=False,
        sandbox_mode_flag=True,
    )
    assert submission_mode(gate) == (None, "spot_not_supported")
