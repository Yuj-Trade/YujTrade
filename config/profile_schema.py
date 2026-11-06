from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from common.constants import TIME_FRAMES

PROFILE_CALLBACK_PREFIX = "pf:"

PENDING_INPUT_SECONDS = 120

PROVIDER_KEY_NAMES: tuple[str, ...] = (
    "CRYPTOPANIC_KEY",
    "ALPHA_VANTAGE_KEY",
    "COINGECKO_KEY",
    "COINDESK_API_KEY",
    "MESSARI_API_KEY",
)

TREND_STRENGTH_CHOICES: tuple[str, ...] = ("WEAK", "MODERATE", "STRONG")
OUTCOME_MODE_CHOICES: tuple[str, ...] = ("off", "shadow", "live")
OUTCOME_KIND_CHOICES: tuple[str, ...] = ("target", "stop", "expired")
LIQUIDITY_CHOICES: tuple[str, ...] = ("maker", "taker")
SCHEDULE_HOUR_KEY = "schedule_hour"

KIND_FLOAT = "float"
KIND_INT = "int"
KIND_BOOL = "bool"
KIND_STR = "str"
KIND_CHOICE = "choice"
KIND_LIST = "list"
KIND_MAP = "map"

SECTION_EXCHANGE_KEYS = "exchange_keys"
SECTION_SERVICE_KEYS = "service_keys"
SECTION_RISK = "risk"
SECTION_STOP_TARGET = "stop_target"
SECTION_ANALYSIS = "analysis"
SECTION_NOTIFICATIONS = "notifications"
SECTION_PAPER = "paper"
SECTION_REPORTING = "reporting"

SECTIONS: tuple[tuple[str, str, str], ...] = (
    (SECTION_EXCHANGE_KEYS, "Exchange keys", "pf:section:exchange_keys"),
    (SECTION_SERVICE_KEYS, "Service keys", "pf:section:service_keys"),
    (SECTION_RISK, "Risk", "pf:section:risk"),
    (SECTION_STOP_TARGET, "Stop and target", "pf:section:stop_target"),
    (SECTION_ANALYSIS, "Analysis", "pf:section:analysis"),
    (SECTION_NOTIFICATIONS, "Notifications and schedule", "pf:section:notifications"),
    (SECTION_PAPER, "Paper and costs", "pf:section:paper"),
    (SECTION_REPORTING, "Reporting", "pf:section:reporting"),
)

TRUE_STRINGS = frozenset({"true", "1", "yes", "on"})
FALSE_STRINGS = frozenset({"false", "0", "no", "off"})

OPERATOR_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "exchange_enabled",
        "exchange_access_profile",
        "exchange_sandbox",
        "exchange_shadow_mode",
        "execution_dry_run",
        "exchange_live_enabled",
        "exchange_live_review_id",
        "exchange_attested_keys",
        "exchange_symbol_allowlist",
        "exchange_max_order_notional_usdt",
        "exchange_max_daily_notional_usdt",
        "exchange_max_price_deviation_pct",
        "exchange_max_spread_pct",
        "TELEGRAM_BOT_TOKEN",
        "ADMIN_CHAT_ID",
        "REDIS_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_USERNAME",
        "REDIS_SSL",
        "REDIS_MAX_CONNECTIONS",
        "REDIS_POOL_TIMEOUT",
        "REDIS_TOKEN",
        "SENTRY_DSN",
        "METRICS_PORT",
        "metrics_enabled",
        "scheduler_db_path",
        "exchange_ledger_path",
        "ohlcv_store_path",
        "feature_store_path",
        "prediction_trace_dir",
        "exchange_reconcile_interval_seconds",
        "exchange_unknown_after_seconds",
        "exchange_request_timeout_ms",
        "exchange_permission_cache_seconds",
        "signal_history_ttl_days",
        "signal_history_max_entries",
        "min_data_points",
        "model_data_limits",
        "model_prediction_limit",
        "model_auto_train_on_predict",
        "paper_fee_rate",
        "paper_slippage_rate",
    }
)

OPERATOR_ONLY_PREFIXES: tuple[str, ...] = (
    "model_learning_",
    "drift_",
    "promotion_",
    "feature_store_",
    "prediction_trace_",
    "ohlcv_store_",
    "model_auto_train",
    "_path",
    "_db_path",
)


@dataclass(frozen=True)
class ProfileEntry:
    key: str
    kind: str
    default: Any
    section: str
    label: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    restart: bool = False
    parent: str = ""
    secret: bool = False


PROFILE_ENTRIES: tuple[ProfileEntry, ...] = (
    ProfileEntry(
        key="coingecko_api_tier",
        kind=KIND_CHOICE,
        default="demo",
        section=SECTION_SERVICE_KEYS,
        label="CoinGecko tier",
        choices=("demo", "pro"),
        restart=True,
    ),
    ProfileEntry(
        key="coindesk_news_enabled",
        kind=KIND_BOOL,
        default=False,
        section=SECTION_SERVICE_KEYS,
        label="CoinDesk news",
        restart=True,
    ),
    ProfileEntry(
        key="messari_enabled",
        kind=KIND_BOOL,
        default=False,
        section=SECTION_SERVICE_KEYS,
        label="Messari feed",
        restart=True,
    ),
    ProfileEntry(
        key="risk_per_trade_pct",
        kind=KIND_FLOAT,
        default=1.0,
        section=SECTION_RISK,
        label="Risk per trade %",
        minimum=0.1,
        maximum=5.0,
    ),
    ProfileEntry(
        key="max_portfolio_exposure_pct",
        kind=KIND_FLOAT,
        default=60.0,
        section=SECTION_RISK,
        label="Max portfolio exposure %",
        minimum=1.0,
        maximum=100.0,
    ),
    ProfileEntry(
        key="max_single_position_pct",
        kind=KIND_FLOAT,
        default=10.0,
        section=SECTION_RISK,
        label="Max single position %",
        minimum=0.1,
        maximum=100.0,
    ),
    ProfileEntry(
        key="max_concurrent_positions",
        kind=KIND_INT,
        default=6,
        section=SECTION_RISK,
        label="Max concurrent positions",
        minimum=1,
        maximum=50,
    ),
    ProfileEntry(
        key="max_daily_loss_pct",
        kind=KIND_FLOAT,
        default=4.0,
        section=SECTION_RISK,
        label="Max daily loss %",
        minimum=0.1,
        maximum=100.0,
    ),
    ProfileEntry(
        key="max_weekly_loss_pct",
        kind=KIND_FLOAT,
        default=10.0,
        section=SECTION_RISK,
        label="Max weekly loss %",
        minimum=0.1,
        maximum=100.0,
    ),
    ProfileEntry(
        key="max_drawdown_pct",
        kind=KIND_FLOAT,
        default=20.0,
        section=SECTION_RISK,
        label="Max drawdown %",
        minimum=0.1,
        maximum=100.0,
    ),
    ProfileEntry(
        key="max_leverage",
        kind=KIND_FLOAT,
        default=3.0,
        section=SECTION_RISK,
        label="Max leverage",
        minimum=1.0,
        maximum=10.0,
    ),
    ProfileEntry(
        key="min_risk_reward",
        kind=KIND_FLOAT,
        default=2.0,
        section=SECTION_RISK,
        label="Minimum risk reward",
        minimum=1.0,
        maximum=10.0,
    ),
    ProfileEntry(
        key="volatility_target_pct",
        kind=KIND_FLOAT,
        default=2.0,
        section=SECTION_RISK,
        label="Volatility target %",
        minimum=0.1,
        maximum=20.0,
    ),
    ProfileEntry(
        key="kelly_fraction",
        kind=KIND_FLOAT,
        default=0.5,
        section=SECTION_RISK,
        label="Kelly fraction",
        minimum=0.0,
        maximum=1.0,
    ),
    ProfileEntry(
        key="loss_streak_threshold",
        kind=KIND_INT,
        default=3,
        section=SECTION_RISK,
        label="Loss streak threshold",
        minimum=1,
        maximum=20,
    ),
    ProfileEntry(
        key="loss_streak_size_multiplier",
        kind=KIND_FLOAT,
        default=0.5,
        section=SECTION_RISK,
        label="Loss streak size multiplier",
        minimum=0.1,
        maximum=1.0,
    ),
    ProfileEntry(
        key="weekly_loss_reduction_ratio",
        kind=KIND_FLOAT,
        default=0.5,
        section=SECTION_RISK,
        label="Weekly loss reduction ratio",
        minimum=0.1,
        maximum=1.0,
    ),
    ProfileEntry(
        key="initial_cash",
        kind=KIND_FLOAT,
        default=10000.0,
        section=SECTION_RISK,
        label="Initial cash",
        minimum=None,
        maximum=None,
        restart=True,
    ),
    ProfileEntry(
        key="stop_atr_multiplier_base",
        kind=KIND_FLOAT,
        default=1.2,
        section=SECTION_STOP_TARGET,
        label="Stop ATR multiplier base",
        minimum=0.5,
        maximum=5.0,
    ),
    ProfileEntry(
        key="stop_atr_multiplier_high_adx",
        kind=KIND_FLOAT,
        default=1.5,
        section=SECTION_STOP_TARGET,
        label="Stop ATR multiplier high ADX",
        minimum=0.5,
        maximum=5.0,
    ),
    ProfileEntry(
        key="stop_adx_threshold",
        kind=KIND_FLOAT,
        default=40.0,
        section=SECTION_STOP_TARGET,
        label="Stop ADX threshold",
        minimum=0.0,
        maximum=100.0,
    ),
    ProfileEntry(
        key="target_min_rr_base",
        kind=KIND_FLOAT,
        default=1.8,
        section=SECTION_STOP_TARGET,
        label="Target min RR base",
        minimum=1.0,
        maximum=10.0,
    ),
    ProfileEntry(
        key="target_min_rr_high_adx",
        kind=KIND_FLOAT,
        default=2.0,
        section=SECTION_STOP_TARGET,
        label="Target min RR high ADX",
        minimum=1.0,
        maximum=10.0,
    ),
    ProfileEntry(
        key="target_adx_threshold",
        kind=KIND_FLOAT,
        default=35.0,
        section=SECTION_STOP_TARGET,
        label="Target ADX threshold",
        minimum=0.0,
        maximum=100.0,
    ),
    ProfileEntry(
        key="stop_use_structure_levels",
        kind=KIND_BOOL,
        default=True,
        section=SECTION_STOP_TARGET,
        label="Stop uses structure levels",
    ),
    ProfileEntry(
        key="target_use_structure_levels",
        kind=KIND_BOOL,
        default=True,
        section=SECTION_STOP_TARGET,
        label="Target uses structure levels",
    ),
    ProfileEntry(
        key="full_analyze_timeframes",
        kind=KIND_LIST,
        default=["1d", "1w", "1M"],
        section=SECTION_ANALYSIS,
        label="Full analyze timeframes",
        choices=TIME_FRAMES,
    ),
    ProfileEntry(
        key="quick_analyze_timeframe",
        kind=KIND_CHOICE,
        default="1h",
        section=SECTION_ANALYSIS,
        label="Quick analyze timeframe",
        choices=TIME_FRAMES,
    ),
    ProfileEntry(
        key="signal_threshold",
        kind=KIND_FLOAT,
        default=10,
        section=SECTION_ANALYSIS,
        label="Signal threshold",
        minimum=0.0,
        maximum=100.0,
    ),
    ProfileEntry(
        key="max_signals_per_timeframe",
        kind=KIND_INT,
        default=1,
        section=SECTION_ANALYSIS,
        label="Max signals per timeframe",
        minimum=1,
        maximum=10,
    ),
    ProfileEntry(
        key="min_confidence_by_timeframe",
        kind=KIND_MAP,
        default={"1h": 82, "4h": 78, "1d": 72, "1w": 68, "1M": 65},
        section=SECTION_ANALYSIS,
        label="Minimum confidence by timeframe",
        minimum=0.0,
        maximum=100.0,
        choices=TIME_FRAMES,
    ),
    ProfileEntry(
        key="min_volume_surge",
        kind=KIND_FLOAT,
        default=1.4,
        section=SECTION_ANALYSIS,
        label="Minimum volume surge",
        minimum=1.0,
        maximum=5.0,
    ),
    ProfileEntry(
        key="min_trend_strength",
        kind=KIND_CHOICE,
        default="MODERATE",
        section=SECTION_ANALYSIS,
        label="Minimum trend strength",
        choices=TREND_STRENGTH_CHOICES,
    ),
    ProfileEntry(
        key="require_higher_tf_confirmation",
        kind=KIND_BOOL,
        default=True,
        section=SECTION_ANALYSIS,
        label="Require higher timeframe confirmation",
        restart=True,
    ),
    ProfileEntry(
        key="max_signals_per_run",
        kind=KIND_INT,
        default=3,
        section=SECTION_ANALYSIS,
        label="Max signals per run",
        minimum=1,
        maximum=20,
    ),
    ProfileEntry(
        key="signal_min_risk_reward_ratio",
        kind=KIND_FLOAT,
        default=2.8,
        section=SECTION_ANALYSIS,
        label="Signal minimum risk reward",
        minimum=1.0,
        maximum=10.0,
    ),
    ProfileEntry(
        key="outcome_notifications_mode",
        kind=KIND_CHOICE,
        default="off",
        section=SECTION_NOTIFICATIONS,
        label="Outcome notifications mode",
        choices=OUTCOME_MODE_CHOICES,
        restart=True,
    ),
    ProfileEntry(
        key="outcome_notification_kinds",
        kind=KIND_LIST,
        default=["target", "stop", "expired"],
        section=SECTION_NOTIFICATIONS,
        label="Outcome notification kinds",
        choices=OUTCOME_KIND_CHOICES,
        restart=True,
    ),
    ProfileEntry(
        key="outcome_notification_timeframes",
        kind=KIND_LIST,
        default=[],
        section=SECTION_NOTIFICATIONS,
        label="Outcome notification timeframes",
        choices=TIME_FRAMES,
        restart=True,
    ),
    ProfileEntry(
        key="enable_scheduled_analysis",
        kind=KIND_BOOL,
        default=False,
        section=SECTION_NOTIFICATIONS,
        label="Scheduled analysis",
        restart=True,
    ),
    ProfileEntry(
        key="schedule_hour",
        kind=KIND_STR,
        default="*/1",
        section=SECTION_NOTIFICATIONS,
        label="Schedule hour",
        restart=True,
    ),
    ProfileEntry(
        key="performance_periods_per_year",
        kind=KIND_INT,
        default=365,
        section=SECTION_REPORTING,
        label="Performance periods per year",
        minimum=1,
        maximum=8760,
    ),
    ProfileEntry(
        key="performance_min_trades_for_ratios",
        kind=KIND_INT,
        default=30,
        section=SECTION_REPORTING,
        label="Minimum trades for ratios",
        minimum=1,
        maximum=1000,
    ),
    ProfileEntry(
        key="performance_rf_annual",
        kind=KIND_FLOAT,
        default=0,
        section=SECTION_REPORTING,
        label="Performance risk free annual",
        minimum=0.0,
        maximum=1.0,
    ),
)

COST_MODEL_ENTRIES: tuple[ProfileEntry, ...] = (
    ProfileEntry(
        key="maker_fee_rate",
        kind=KIND_FLOAT,
        default=0.001,
        section=SECTION_PAPER,
        label="Maker fee rate",
        minimum=0.0,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="taker_fee_rate",
        kind=KIND_FLOAT,
        default=0.001,
        section=SECTION_PAPER,
        label="Taker fee rate",
        minimum=0.0,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="entry_slippage_rate",
        kind=KIND_FLOAT,
        default=0.0005,
        section=SECTION_PAPER,
        label="Entry slippage rate",
        minimum=0.0,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="market_exit_slippage_rate",
        kind=KIND_FLOAT,
        default=0.0005,
        section=SECTION_PAPER,
        label="Market exit slippage rate",
        minimum=0.0,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="target_exit_slippage_rate",
        kind=KIND_FLOAT,
        default=0.0,
        section=SECTION_PAPER,
        label="Target exit slippage rate",
        minimum=0.0,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="funding_rate_per_period",
        kind=KIND_FLOAT,
        default=0.0001,
        section=SECTION_PAPER,
        label="Funding rate per period",
        minimum=0.0,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="funding_period_hours",
        kind=KIND_INT,
        default=8,
        section=SECTION_PAPER,
        label="Funding period hours",
        minimum=0,
        maximum=24,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="max_volume_participation",
        kind=KIND_FLOAT,
        default=0.05,
        section=SECTION_PAPER,
        label="Max volume participation",
        minimum=0.0,
        maximum=1.0,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="entry_liquidity",
        kind=KIND_CHOICE,
        default="taker",
        section=SECTION_PAPER,
        label="Entry liquidity",
        choices=LIQUIDITY_CHOICES,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="target_exit_liquidity",
        kind=KIND_CHOICE,
        default="maker",
        section=SECTION_PAPER,
        label="Target exit liquidity",
        choices=LIQUIDITY_CHOICES,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="stop_exit_liquidity",
        kind=KIND_CHOICE,
        default="taker",
        section=SECTION_PAPER,
        label="Stop exit liquidity",
        choices=LIQUIDITY_CHOICES,
        parent="paper_cost_model",
    ),
    ProfileEntry(
        key="expiry_exit_liquidity",
        kind=KIND_CHOICE,
        default="taker",
        section=SECTION_PAPER,
        label="Expiry exit liquidity",
        choices=LIQUIDITY_CHOICES,
        parent="paper_cost_model",
    ),
)

ALL_ENTRIES: tuple[ProfileEntry, ...] = PROFILE_ENTRIES + COST_MODEL_ENTRIES

_ENTRIES_BY_KEY: dict[str, ProfileEntry] = {entry.key: entry for entry in ALL_ENTRIES}

GATE_KEY_ALIASES: dict[str, str] = {
    "min_confidence_threshold": "min_confidence_by_timeframe",
    "min_trend_strength": "min_trend_strength",
    "min_volume_surge": "min_volume_surge",
    "min_risk_reward_ratio": "signal_min_risk_reward_ratio",
    "max_signals_per_run": "max_signals_per_run",
    "require_higher_tf_confirmation": "require_higher_tf_confirmation",
    "focus_timeframes": "full_analyze_timeframes",
}


def entries_for_section(section: str) -> tuple[ProfileEntry, ...]:
    return tuple(entry for entry in ALL_ENTRIES if entry.section == section)


def get_entry(key: str) -> ProfileEntry | None:
    return _ENTRIES_BY_KEY.get(key)


def is_operator_only(key: str) -> bool:
    if key in OPERATOR_ONLY_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in OPERATOR_ONLY_PREFIXES)


def parse_bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUE_STRINGS:
            return True
        if normalized in FALSE_STRINGS:
            return False
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    if number != int(number):
        return None
    return int(number)


def _as_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return str(value)
    return None


def _match_choice(text: str | None, choices: tuple[str, ...]) -> str | None:
    if text is None:
        return None
    for choice in choices:
        if str(choice) == text:
            return str(choice)
    lowered = text.lower()
    for choice in choices:
        if str(choice).lower() == lowered:
            return str(choice)
    return None


def parse_list_value(value: Any, allowed: tuple[str, ...]) -> list[str] | None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        items = [item.strip().strip("\"'").strip() for item in text.split(",")]
        candidates = [item for item in items if item]
    elif isinstance(value, (list, tuple)):
        candidates = [str(item).strip() for item in value if str(item).strip()]
    else:
        return None
    if allowed:
        unknown = [item for item in candidates if item not in allowed]
        if unknown:
            return None
    return candidates


def parse_map_value(
    value: Any, allowed: tuple[str, ...], minimum: float | None, maximum: float | None
) -> dict[str, float] | None:
    if isinstance(value, str):
        text = value.strip()
        if not text.startswith("{"):
            return None
        body = text.strip("{}").strip()
        if not body:
            return {}
        parsed: dict[str, float] = {}
        for chunk in body.split(","):
            if ":" not in chunk:
                return None
            raw_key, raw_number = chunk.split(":", 1)
            key = raw_key.strip().strip("\"'").strip()
            number = _as_float(raw_number.strip().strip("\"'"))
            if not key or number is None:
                return None
            parsed[key] = number
    elif isinstance(value, dict):
        parsed = {}
        for key, raw_number in value.items():
            number = _as_float(raw_number)
            if number is None:
                return None
            parsed[str(key)] = number
    else:
        return None
    if allowed:
        unknown = [key for key in parsed if key not in allowed]
        if unknown:
            return None
    for number in parsed.values():
        if minimum is not None and number < minimum:
            return None
        if maximum is not None and number > maximum:
            return None
    return parsed


def is_valid_schedule_hour(value: str) -> bool:
    text = str(value).strip()
    if not text:
        return False
    try:
        hours = float(text[2:]) if text.startswith("*/") else float(text)
    except ValueError:
        return False
    return hours > 0


def parse_value(entry: ProfileEntry, raw: Any) -> tuple[bool, Any, str]:
    if entry.kind == KIND_BOOL:
        parsed = parse_bool_value(raw)
        if parsed is None:
            return False, entry.default, f"{entry.label}: expected a boolean value"
        return True, parsed, ""
    if entry.kind in (KIND_FLOAT, KIND_INT):
        number = _as_float(raw)
        if number is None:
            return False, entry.default, f"{entry.label}: expected a number"
        if entry.kind == KIND_INT:
            whole = _as_int(raw)
            if whole is None:
                return False, entry.default, f"{entry.label}: expected a whole number"
            number = float(whole)
        if entry.minimum is not None and number < float(entry.minimum):
            return False, entry.default, _range_message(entry)
        if entry.maximum is not None and number > float(entry.maximum):
            return False, entry.default, _range_message(entry)
        if entry.kind == KIND_INT:
            return True, int(number), ""
        return True, float(number), ""
    if entry.kind == KIND_CHOICE:
        text = _as_text(raw)
        chosen = _match_choice(text, entry.choices)
        if chosen is None:
            allowed = ", ".join(str(choice) for choice in entry.choices)
            return False, entry.default, f"{entry.label}: choose one of {allowed}"
        return True, chosen, ""
    if entry.kind == KIND_STR:
        text = _as_text(raw)
        if text is None or not text:
            return False, entry.default, f"{entry.label}: expected text"
        if entry.key == SCHEDULE_HOUR_KEY and not is_valid_schedule_hour(text):
            return False, entry.default, f"{entry.label}: use a positive number or */N"
        return True, text, ""
    if entry.kind == KIND_LIST:
        parsed = parse_list_value(raw, entry.choices)
        if parsed is None:
            allowed = ", ".join(str(choice) for choice in entry.choices)
            return False, entry.default, f"{entry.label}: choose from {allowed}"
        return True, parsed, ""
    parsed = parse_map_value(raw, entry.choices, entry.minimum, entry.maximum)
    if parsed is None:
        allowed = ", ".join(str(choice) for choice in entry.choices)
        return (
            False,
            entry.default,
            f"{entry.label}: send {'{'}timeframe: number{'}'} from {allowed}",
        )
    return True, parsed, ""


def _range_message(entry: ProfileEntry) -> str:
    if entry.minimum is not None and entry.maximum is not None:
        span = f"{entry.minimum:g} to {entry.maximum:g}"
    elif entry.minimum is not None:
        span = f"at least {entry.minimum:g}"
    elif entry.maximum is not None:
        return f"{entry.label}: at most {entry.maximum:g}"
    else:
        span = "greater than 0"
    return f"{entry.label}: expected {span}"


_MISSING = object()


def gate_getter(config_manager: Any) -> Callable[[str, Any], Any]:
    def get(key: str, default: Any = None) -> Any:
        alias = GATE_KEY_ALIASES.get(key)
        if alias is not None:
            entry = _ENTRIES_BY_KEY.get(alias)
            stored = config_manager.get(alias, _MISSING)
            if entry is not None and stored is not _MISSING and stored != entry.default:
                return stored
        return default

    return get


def chained_getter(
    config_manager: Any, base: Callable[[str, Any], Any]
) -> Callable[[str, Any], Any]:
    profile = gate_getter(config_manager)

    def get(key: str, default: Any = None) -> Any:
        value = profile(key, _MISSING)
        if value is not _MISSING:
            return value
        return base(key, default)

    return get


def format_value(entry: ProfileEntry, value: Any) -> str:
    if entry.kind == KIND_BOOL:
        return "on" if value else "off"
    if entry.kind == KIND_LIST:
        return ", ".join(str(item) for item in value) if value else "all"
    if entry.kind == KIND_MAP:
        return ", ".join(f"{key}: {value[key]:g}" for key in sorted(value))
    if entry.kind in (KIND_FLOAT,):
        return f"{float(value):g}"
    return str(value)


def current_value(config_manager: Any, entry: ProfileEntry) -> Any:
    if entry.parent:
        model = config_manager.get(entry.parent, {}) or {}
        if entry.key in model:
            return model[entry.key]
        return entry.default
    stored = config_manager.get(entry.key, _MISSING)
    if stored is _MISSING:
        return entry.default
    return stored


def set_profile_value(config_manager: Any, key: str, raw: Any) -> tuple[bool, str]:
    if is_operator_only(key):
        return False, "That setting is operator-only and cannot be changed here."
    entry = get_entry(key)
    if entry is None:
        return False, "Unknown profile setting."
    accepted, value, message = parse_value(entry, raw)
    if not accepted:
        return False, message
    if entry.parent:
        model = dict(config_manager.get(entry.parent, {}) or {})
        model[entry.key] = value
        config_manager.set(entry.parent, model)
        return True, ""
    if entry.kind == KIND_MAP:
        merged = dict(current_value(config_manager, entry) or {})
        merged.update(value)
        config_manager.set(entry.key, merged)
        return True, ""
    config_manager.set(entry.key, value)
    return True, ""


def reset_profile_value(config_manager: Any, key: str) -> tuple[bool, str]:
    if is_operator_only(key):
        return False, "That setting is operator-only and cannot be changed here."
    entry = get_entry(key)
    if entry is None:
        return False, "Unknown profile setting."
    if entry.parent:
        model = dict(config_manager.get(entry.parent, {}) or {})
        model[entry.key] = entry.default
        config_manager.set(entry.parent, model)
        return True, ""
    config_manager.set(entry.key, entry.default)
    return True, ""
