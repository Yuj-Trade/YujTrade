import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from application.exchange_policy import (
    PROFILE_GENERAL,
    PROFILE_IRAN,
    STATUS_READY,
    GateInput,
    scope_matches_profile,
)
from config.logger import logger
from config.settings import ConfigManager
from trading.exchanges.registry import ExchangeSpec

_REVIEW_ID_PATTERN = re.compile(r"^ADR-\d{4}$")


@dataclass(frozen=True)
class ExchangeSettings:
    enabled: tuple[str, ...]
    access_profile: str
    sandbox: bool
    shadow_mode: bool
    live_enabled: bool
    live_review_id: str
    attested_keys: tuple[str, ...]
    symbol_allowlist: tuple[str, ...]
    max_order_notional: float
    max_daily_notional: float
    max_deviation_pct: float
    max_spread_pct: float
    ledger_path: str
    reconcile_interval_seconds: float
    unknown_after_seconds: float
    request_timeout_ms: int


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value)


def load_exchange_settings(config_manager: ConfigManager) -> ExchangeSettings:
    defaults = ConfigManager.DEFAULT_CONFIG

    def value(key: str) -> Any:
        return config_manager.get(key, defaults.get(key))

    return ExchangeSettings(
        enabled=_as_tuple(value("exchange_enabled")),
        access_profile=str(value("exchange_access_profile")),
        sandbox=bool(value("exchange_sandbox")),
        shadow_mode=bool(value("exchange_shadow_mode")),
        live_enabled=bool(value("exchange_live_enabled")),
        live_review_id=str(value("exchange_live_review_id")),
        attested_keys=_as_tuple(value("exchange_attested_keys")),
        symbol_allowlist=_as_tuple(value("exchange_symbol_allowlist")),
        max_order_notional=float(value("exchange_max_order_notional_usdt")),
        max_daily_notional=float(value("exchange_max_daily_notional_usdt")),
        max_deviation_pct=float(value("exchange_max_price_deviation_pct")),
        max_spread_pct=float(value("exchange_max_spread_pct")),
        ledger_path=str(value("exchange_ledger_path")),
        reconcile_interval_seconds=float(value("exchange_reconcile_interval_seconds")),
        unknown_after_seconds=float(value("exchange_unknown_after_seconds")),
        request_timeout_ms=int(value("exchange_request_timeout_ms")),
    )


def review_is_accepted(review_id: str, adr_dir: Path | str = Path("docs/adr")) -> bool:
    if not review_id or not _REVIEW_ID_PATTERN.match(review_id):
        return False
    directory = Path(adr_dir)
    if not directory.is_dir():
        return False
    matches = sorted(directory.glob(f"{review_id}-*.md"))
    if not matches:
        logger.warning(f"Review id {review_id} has no ADR file")
        return False
    for path in matches:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().lower().startswith("status:"):
                status = line.split(":", 1)[1].strip().lower()
                return status.startswith("accepted")
    return False


def profile_accepts(profile: str, spec: ExchangeSpec) -> bool:
    if profile not in {PROFILE_GENERAL, PROFILE_IRAN}:
        return False
    return scope_matches_profile(spec.access_scope, profile)


def build_gate_input(
    spec: ExchangeSpec,
    settings: ExchangeSettings,
    creds_ok: bool,
    permissions_ok: bool,
    halted: bool,
    sandbox_mode_flag: bool,
    execution_dry_run: bool = True,
    review_ok: bool | None = None,
) -> GateInput:
    resolved_review = (
        review_is_accepted(settings.live_review_id) if review_ok is None else review_ok
    )
    return GateInput(
        status_ready=spec.status == STATUS_READY,
        spot_supported=spec.spot_supported,
        scope_ok=profile_accepts(settings.access_profile, spec),
        exchange_enabled=spec.exchange_id in settings.enabled,
        halted=halted,
        credentials_ok=creds_ok,
        sandbox=sandbox_mode_flag,
        shadow_mode=settings.shadow_mode,
        execution_dry_run=execution_dry_run,
        live_enabled=settings.live_enabled,
        review_ok=resolved_review,
        attested=spec.exchange_id in settings.attested_keys,
        permissions_ok=permissions_ok,
    )
