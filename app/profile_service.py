from typing import Any

from config.logger import logger
from config.profile_schema import (
    ProfileEntry,
    current_value,
    entries_for_section,
    get_entry,
    reset_profile_value,
    set_profile_value,
)
from trading.risk_manager import RISK_CONFIG_FIELDS

RESTART_NOTE = "applies after restart"
APPLIED_NOTE = "applied"

GATE_KEYS = frozenset(
    {
        "min_confidence_by_timeframe",
        "min_trend_strength",
        "min_volume_surge",
        "require_higher_tf_confirmation",
        "max_signals_per_run",
        "signal_min_risk_reward_ratio",
        "full_analyze_timeframes",
    }
)


class ProfileService:
    def __init__(
        self,
        config_manager: Any,
        trading_service: Any = None,
        market_data_provider: Any = None,
    ):
        self.config_manager = config_manager
        self.trading_service = trading_service
        self.market_data_provider = market_data_provider

    def entries(self, section: str) -> tuple[ProfileEntry, ...]:
        return entries_for_section(section)

    def current(self, key: str) -> Any:
        entry = get_entry(key)
        if entry is None:
            return None
        return current_value(self.config_manager, entry)

    def is_default(self, key: str) -> bool:
        entry = get_entry(key)
        if entry is None:
            return True
        return current_value(self.config_manager, entry) == entry.default

    def save(self, key: str, raw: Any) -> tuple[bool, str, str]:
        ok, message = set_profile_value(self.config_manager, key, raw)
        if not ok:
            return False, message, ""
        return True, self._applied_note(key), self._apply(key)

    def reset(self, key: str) -> tuple[bool, str, str]:
        ok, message = reset_profile_value(self.config_manager, key)
        if not ok:
            return False, message, ""
        return True, self._applied_note(key), self._apply(key)

    def _applied_note(self, key: str) -> str:
        entry = get_entry(key)
        if entry is None or entry.restart:
            return RESTART_NOTE
        return APPLIED_NOTE

    def _apply(self, key: str) -> str:
        if key in RISK_CONFIG_FIELDS:
            self._apply_risk()
            return APPLIED_NOTE
        entry = get_entry(key)
        if entry is not None and entry.parent:
            return self._apply_cost_model()
        if key in GATE_KEYS:
            return APPLIED_NOTE
        return self._applied_note(key)

    def _apply_risk(self) -> None:
        risk_manager = getattr(self.trading_service, "risk_manager", None)
        if risk_manager is None:
            return
        from trading.risk_manager import build_risk_config

        fresh = build_risk_config(self.config_manager)
        for field in RISK_CONFIG_FIELDS:
            setattr(risk_manager.config, field, getattr(fresh, field))

    def _apply_cost_model(self) -> str:
        engine = getattr(self.trading_service, "paper_engine", None)
        if engine is None:
            return RESTART_NOTE
        from services.trading_service import build_cost_profile

        try:
            profile = build_cost_profile(self.config_manager)
        except (ValueError, TypeError) as exc:
            logger.warning(f"Cost model update refused: {exc}")
            return RESTART_NOTE
        engine.cost_profile = profile
        return APPLIED_NOTE

    def rebuild_provider_fetchers(self) -> None:
        provider = self.market_data_provider
        if provider is None:
            return
        rebuild = getattr(provider, "rebuild_keyed_fetchers", None)
        if rebuild is not None:
            rebuild()

    def drop_venue_state(self, exchange_id: str) -> None:
        exchange_service = getattr(self.trading_service, "exchange_service", None)
        drop = getattr(exchange_service, "drop_venue_state", None)
        if drop is not None:
            drop(exchange_id)
        self._reset_attestation(exchange_id)

    def _reset_attestation(self, exchange_id: str) -> None:
        attested = self.config_manager.get("exchange_attested_keys", []) or []
        if exchange_id not in attested:
            return
        remaining = [item for item in attested if str(item) != exchange_id]
        self.config_manager.set("exchange_attested_keys", remaining)
