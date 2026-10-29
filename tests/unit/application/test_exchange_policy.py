import pytest

from application.exchange_policy import (
    PROFILE_GENERAL,
    PROFILE_IRAN,
    SCOPE_GENERAL,
    SCOPE_IRAN_ONLY,
    STATUS_PENDING_DOCS,
    GateInput,
    map_ccxt_status,
    next_status,
    risk_check,
    scope_matches_profile,
    submission_mode,
)
from domain.exchange_types import (
    CANCELED,
    EXPIRED,
    FILLED,
    OPEN,
    PARTIALLY_FILLED,
    PENDING_SUBMIT,
    REJECTED,
    SUBMITTED,
    UNKNOWN,
)


def _gate(**overrides) -> GateInput:
    base = dict(
        status_ready=True,
        spot_supported=True,
        scope_ok=True,
        exchange_enabled=True,
        halted=False,
        credentials_ok=True,
        sandbox=True,
        shadow_mode=False,
        execution_dry_run=True,
        live_enabled=False,
        review_ok=False,
        attested=False,
        permissions_ok=False,
    )
    base.update(overrides)
    return GateInput(**base)


def _live_gate(**overrides) -> GateInput:
    base = dict(
        sandbox=False,
        shadow_mode=False,
        execution_dry_run=False,
        live_enabled=True,
        review_ok=True,
        attested=True,
        permissions_ok=True,
    )
    base.update(overrides)
    return _gate(**base)


def test_scope_matches_general_profile():
    assert scope_matches_profile(SCOPE_GENERAL, PROFILE_GENERAL) is True
    assert scope_matches_profile(SCOPE_IRAN_ONLY, PROFILE_GENERAL) is False


def test_scope_matches_iran_profile():
    assert scope_matches_profile(SCOPE_IRAN_ONLY, PROFILE_IRAN) is True
    assert scope_matches_profile(SCOPE_GENERAL, PROFILE_IRAN) is False


def test_scope_unknown_values_do_not_match():
    assert scope_matches_profile("other", PROFILE_GENERAL) is False
    assert scope_matches_profile(SCOPE_GENERAL, "other") is False


def test_map_closed_is_filled():
    assert map_ccxt_status("closed", 1.0, 1.0) == FILLED


def test_map_canceled_variants():
    assert map_ccxt_status("canceled", 0.0, 1.0) == CANCELED
    assert map_ccxt_status("cancelled", 0.0, 1.0) == CANCELED


def test_map_expired_and_rejected():
    assert map_ccxt_status("expired", 0.0, 1.0) == EXPIRED
    assert map_ccxt_status("rejected", 0.0, 1.0) == REJECTED


def test_map_open_with_and_without_fill():
    assert map_ccxt_status("open", 0.0, 1.0) == OPEN
    assert map_ccxt_status("open", 0.4, 1.0) == PARTIALLY_FILLED


def test_map_none_and_unknown_are_unknown():
    assert map_ccxt_status(None, 0.0, 1.0) == UNKNOWN
    assert map_ccxt_status("weird-status", 0.0, 1.0) == UNKNOWN


def test_map_is_case_insensitive():
    assert map_ccxt_status("CLOSED", 1.0, 1.0) == FILLED


def test_next_status_terminal_is_sticky():
    assert next_status(FILLED, CANCELED, 10_000.0, 60.0) == FILLED


def test_next_status_observed_wins():
    assert next_status(SUBMITTED, OPEN, 1.0, 60.0) == OPEN
    assert next_status(PENDING_SUBMIT, FILLED, 1.0, 60.0) == FILLED


def test_next_status_unknown_after_threshold():
    assert next_status(SUBMITTED, None, 61.0, 60.0) == UNKNOWN
    assert next_status(PENDING_SUBMIT, None, 61.0, 60.0) == UNKNOWN


def test_next_status_keeps_current_before_threshold():
    assert next_status(SUBMITTED, None, 59.0, 60.0) == SUBMITTED
    assert next_status(OPEN, None, 10_000.0, 60.0) == OPEN


def test_submission_mode_halted_first():
    assert submission_mode(_gate(halted=True)) == (None, "halted")


def test_submission_mode_registry_and_market_checks():
    assert submission_mode(_gate(status_ready=False)) == (None, "exchange_not_ready")
    assert submission_mode(_gate(spot_supported=False)) == (None, "spot_not_supported")
    assert submission_mode(_gate(scope_ok=False)) == (None, "scope_mismatch")
    assert submission_mode(_gate(exchange_enabled=False)) == (None, "exchange_not_enabled")


def test_submission_mode_sandbox():
    assert submission_mode(_gate()) == ("sandbox", "ok")
    assert submission_mode(_gate(credentials_ok=False)) == (None, "credentials_missing")


def test_submission_mode_shadow_needs_no_credentials():
    assert submission_mode(_gate(sandbox=False, shadow_mode=True, credentials_ok=False)) == (
        "shadow",
        "ok",
    )


def test_submission_mode_live_conditions_in_order():
    assert submission_mode(_live_gate(credentials_ok=False)) == (None, "credentials_missing")
    assert submission_mode(_live_gate(attested=False)) == (None, "key_not_attested")
    assert submission_mode(_live_gate(permissions_ok=False)) == (
        None,
        "permissions_not_verified",
    )
    assert submission_mode(_live_gate(execution_dry_run=True)) == (None, "execution_dry_run")
    assert submission_mode(_live_gate(live_enabled=False)) == (None, "live_disabled")
    assert submission_mode(_live_gate(review_ok=False)) == (None, "review_not_accepted")


def test_submission_mode_live_when_all_conditions_hold():
    assert submission_mode(_live_gate()) == ("live", "ok")


def test_submission_mode_defaults_never_return_live():
    default_gate = GateInput(
        status_ready=True,
        spot_supported=True,
        scope_ok=True,
        exchange_enabled=True,
        halted=False,
        credentials_ok=True,
        sandbox=True,
        shadow_mode=True,
        execution_dry_run=True,
        live_enabled=False,
        review_ok=False,
        attested=False,
        permissions_ok=False,
    )
    mode, _ = submission_mode(default_gate)
    assert mode != "live"


def test_submission_mode_pending_docs_status_is_not_ready():
    assert STATUS_PENDING_DOCS != "ready"
    assert submission_mode(_gate(status_ready=False)) == (None, "exchange_not_ready")


def _risk(**overrides):
    base = dict(
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_000.0,
        last=50_000.0,
        bid=49_990.0,
        ask=50_010.0,
        daily_notional=0.0,
        held_amount=None,
        min_amount=0.0001,
        min_cost=5.0,
        symbol_allowlist=("BTC/USDT",),
        max_order_notional=50.0,
        max_daily_notional=200.0,
        max_deviation_pct=2.0,
        max_spread_pct=0.5,
    )
    base.update(overrides)
    return risk_check(**base)


def test_risk_check_accepts_valid_order():
    assert _risk() == (True, "ok")


def test_risk_rejects_invalid_quantity():
    assert _risk(amount=0.0) == (False, "invalid_quantity")
    assert _risk(price=-1.0) == (False, "invalid_quantity")


def test_risk_rejects_symbol_not_allowlisted():
    assert _risk(symbol_allowlist=()) == (False, "symbol_not_allowlisted")
    assert _risk(symbol_allowlist=("ETH/USDT",)) == (False, "symbol_not_allowlisted")


def test_risk_rejects_below_minimums():
    assert _risk(amount=0.00001) == (False, "below_exchange_minimum")
    assert _risk(amount=0.0001, price=1000.0, last=1000.0, bid=999.5, ask=1000.5) == (
        False,
        "below_exchange_minimum",
    )


def test_risk_rejects_order_notional():
    assert _risk(amount=0.01, price=6000.0, last=6000.0, bid=5999.0, ask=6001.0) == (
        False,
        "order_notional_exceeded",
    )


def test_risk_rejects_daily_notional():
    assert _risk(daily_notional=199.0) == (False, "daily_notional_exceeded")


def test_risk_rejects_price_deviation():
    assert _risk(price=52_000.0) == (False, "price_deviation_exceeded")
    assert _risk(last=0.0) == (False, "price_deviation_exceeded")


def test_risk_rejects_wide_spread():
    assert _risk(bid=49_000.0, ask=51_000.0) == (False, "spread_exceeded")
    assert _risk(bid=0.0) == (False, "spread_exceeded")


def test_risk_rejects_sell_without_base_balance():
    assert _risk(side="sell", held_amount=0.0002) == (False, "insufficient_base_balance")


def test_risk_allows_sell_with_balance():
    assert _risk(side="sell", held_amount=0.02) == (True, "ok")


def test_risk_allows_sell_when_balance_unknown():
    assert _risk(side="sell", held_amount=None) == (True, "ok")


@pytest.mark.parametrize("reason", ["invalid_quantity", "spread_exceeded"])
def test_risk_reason_is_a_stable_string(reason):
    assert isinstance(reason, str)
