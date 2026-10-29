from collections.abc import Sequence
from dataclasses import dataclass

from domain.exchange_types import (
    CANCELED,
    EXPIRED,
    FILLED,
    OPEN,
    PARTIALLY_FILLED,
    PENDING_SUBMIT,
    REJECTED,
    SUBMITTED,
    TERMINAL_STATUSES,
    UNKNOWN,
)

SCOPE_GENERAL = "general"
SCOPE_IRAN_ONLY = "iran_users_only"
PROFILE_GENERAL = "general"
PROFILE_IRAN = "iran"
STATUS_READY = "ready"
STATUS_PENDING_DOCS = "pending_docs_verification"

MODES_WITHOUT_CREDENTIALS = ("shadow",)


@dataclass(frozen=True)
class GateInput:
    status_ready: bool
    spot_supported: bool
    scope_ok: bool
    exchange_enabled: bool
    halted: bool
    credentials_ok: bool
    sandbox: bool
    shadow_mode: bool
    execution_dry_run: bool
    live_enabled: bool
    review_ok: bool
    attested: bool
    permissions_ok: bool


def scope_matches_profile(scope: str, profile: str) -> bool:
    if scope == SCOPE_GENERAL and profile == PROFILE_GENERAL:
        return True
    if scope == SCOPE_IRAN_ONLY and profile == PROFILE_IRAN:
        return True
    return False


def map_ccxt_status(raw_status: str | None, filled: float, amount: float) -> str:
    if raw_status is None:
        return UNKNOWN
    normalized = str(raw_status).strip().lower()
    if normalized == "closed":
        return FILLED
    if normalized in {"canceled", "cancelled"}:
        return CANCELED
    if normalized == "expired":
        return EXPIRED
    if normalized == "rejected":
        return REJECTED
    if normalized == "open":
        if filled > 0:
            return PARTIALLY_FILLED
        return OPEN
    return UNKNOWN


def next_status(
    current: str, observed: str | None, age_seconds: float, unknown_after_seconds: float
) -> str:
    if current in TERMINAL_STATUSES:
        return current
    if observed is not None:
        return observed
    if current in {PENDING_SUBMIT, SUBMITTED} and age_seconds > unknown_after_seconds:
        return UNKNOWN
    return current


def submission_mode(inp: GateInput) -> tuple[str | None, str]:
    if inp.halted:
        return None, "halted"
    if not inp.status_ready:
        return None, "exchange_not_ready"
    if not inp.spot_supported:
        return None, "spot_not_supported"
    if not inp.scope_ok:
        return None, "scope_mismatch"
    if not inp.exchange_enabled:
        return None, "exchange_not_enabled"
    if inp.sandbox:
        if not inp.credentials_ok:
            return None, "credentials_missing"
        return "sandbox", "ok"
    if inp.shadow_mode:
        return "shadow", "ok"
    if not inp.credentials_ok:
        return None, "credentials_missing"
    if not inp.attested:
        return None, "key_not_attested"
    if not inp.permissions_ok:
        return None, "permissions_not_verified"
    if inp.execution_dry_run:
        return None, "execution_dry_run"
    if not inp.live_enabled:
        return None, "live_disabled"
    if not inp.review_ok:
        return None, "review_not_accepted"
    return "live", "ok"


def risk_check(
    symbol: str,
    side: str,
    amount: float,
    price: float,
    last: float,
    bid: float,
    ask: float,
    daily_notional: float,
    held_amount: float | None,
    min_amount: float,
    min_cost: float,
    symbol_allowlist: Sequence[str],
    max_order_notional: float,
    max_daily_notional: float,
    max_deviation_pct: float,
    max_spread_pct: float,
) -> tuple[bool, str]:
    if amount <= 0 or price <= 0:
        return False, "invalid_quantity"
    if not symbol_allowlist or symbol not in symbol_allowlist:
        return False, "symbol_not_allowlisted"
    if amount < min_amount or amount * price < min_cost:
        return False, "below_exchange_minimum"
    notional = amount * price
    if notional > max_order_notional:
        return False, "order_notional_exceeded"
    if daily_notional + notional > max_daily_notional:
        return False, "daily_notional_exceeded"
    if last <= 0 or abs(price - last) / last * 100.0 > max_deviation_pct:
        return False, "price_deviation_exceeded"
    mid = (bid + ask) / 2.0
    if bid <= 0 or ask <= 0 or mid <= 0 or (ask - bid) / mid * 100.0 > max_spread_pct:
        return False, "spread_exceeded"
    if side == "sell" and held_amount is not None and held_amount < amount:
        return False, "insufficient_base_balance"
    return True, "ok"
