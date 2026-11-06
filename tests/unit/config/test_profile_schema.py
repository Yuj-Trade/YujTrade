import pytest

from config.profile_schema import (
    ALL_ENTRIES,
    COST_MODEL_ENTRIES,
    KIND_BOOL,
    KIND_CHOICE,
    KIND_FLOAT,
    KIND_INT,
    KIND_LIST,
    KIND_MAP,
    KIND_STR,
    PROVIDER_KEY_NAMES,
    current_value,
    get_entry,
    is_operator_only,
    is_valid_schedule_hour,
    parse_value,
    reset_profile_value,
    set_profile_value,
)
from config.settings import ConfigManager


class RecordingConfig:
    def __init__(self):
        self.config = dict(ConfigManager.DEFAULT_CONFIG)
        self.saved = {}

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.saved[key] = value
        self.config[key] = value


TEXTUAL_KINDS = {
    KIND_FLOAT,
    KIND_INT,
    KIND_BOOL,
    KIND_CHOICE,
    KIND_STR,
    KIND_LIST,
    KIND_MAP,
}


def test_every_entry_declares_a_type_and_a_bound():
    for entry in ALL_ENTRIES:
        assert entry.kind in TEXTUAL_KINDS, entry.key
        if entry.kind in (KIND_FLOAT, KIND_INT):
            has_bounds = entry.minimum is not None or entry.maximum is not None
            has_bounds = has_bounds or entry.key == "initial_cash"
            assert has_bounds, entry.key
        elif entry.kind != KIND_BOOL:
            assert entry.choices or entry.kind == KIND_STR, entry.key


def test_schema_defaults_equal_default_config():
    defaults = ConfigManager.DEFAULT_CONFIG
    for entry in ALL_ENTRIES:
        if entry.parent:
            assert defaults[entry.parent][entry.key] == entry.default, entry.key
        else:
            assert entry.key in defaults, entry.key
            assert defaults[entry.key] == entry.default, entry.key


def test_cost_model_schema_hides_legacy_and_version_keys():
    keys = {entry.key for entry in COST_MODEL_ENTRIES}
    assert "version" not in keys
    assert "paper_fee_rate" not in keys
    assert "paper_slippage_rate" not in keys
    assert "maker_fee_rate" in keys
    assert "max_volume_participation" in keys


def test_provider_keys_are_optional_and_complete():
    assert set(PROVIDER_KEY_NAMES) == {
        "CRYPTOPANIC_KEY",
        "ALPHA_VANTAGE_KEY",
        "COINGECKO_KEY",
        "COINDESK_API_KEY",
        "MESSARI_API_KEY",
    }


@pytest.mark.parametrize(
    "key,raw",
    [
        ("risk_per_trade_pct", "0.05"),
        ("risk_per_trade_pct", "7"),
        ("risk_per_trade_pct", "text"),
        ("max_leverage", "0.5"),
        ("max_concurrent_positions", "3.5"),
        ("max_concurrent_positions", "51"),
        ("kelly_fraction", "1.5"),
        ("min_trend_strength", "VERY_STRONG"),
        ("coingecko_api_tier", "enterprise"),
        ("quick_analyze_timeframe", "2h"),
        ("full_analyze_timeframes", "2h,7d"),
        ("outcome_notification_kinds", "target,cancelled"),
        ("outcome_notifications_mode", "loud"),
        ("schedule_hour", "hourly"),
        ("schedule_hour", "*/0"),
        ("min_confidence_by_timeframe", "{1h: 200}"),
        ("min_confidence_by_timeframe", "{3h: 80}"),
        ("entry_liquidity", "both"),
        ("max_daily_loss_pct", True),
    ],
)
def test_out_of_range_or_wrong_type_values_are_rejected(key, raw):
    config = RecordingConfig()
    entry = get_entry(key)
    accepted, value, message = parse_value(entry, raw)
    assert accepted is False
    assert message
    assert value == entry.default
    ok, _ = set_profile_value(config, key, raw)
    assert ok is False


@pytest.mark.parametrize(
    "key,raw,expected",
    [
        ("risk_per_trade_pct", "2.5", 2.5),
        ("max_concurrent_positions", "4", 4),
        ("stop_use_structure_levels", "yes", True),
        ("stop_use_structure_levels", "off", False),
        ("stop_use_structure_levels", "1", True),
        ("min_trend_strength", "strong", "STRONG"),
        ("full_analyze_timeframes", "1d, 1M", ["1d", "1M"]),
        ("full_analyze_timeframes", '["4h"]', ["4h"]),
        ("outcome_notification_timeframes", [], []),
        (
            "min_confidence_by_timeframe",
            "{1h: 90}",
            {"1h": 90, "4h": 78, "1d": 72, "1w": 68, "1M": 65},
        ),
        ("schedule_hour", "*/6", "*/6"),
        ("entry_liquidity", "maker", "maker"),
        ("initial_cash", "25000", 25000.0),
    ],
)
def test_valid_values_are_parsed_and_saved(key, raw, expected):
    config = RecordingConfig()
    ok, _ = set_profile_value(config, key, raw)
    assert ok is True
    entry = get_entry(key)
    assert current_value(config, entry) == expected


def test_boolean_parsing_rejects_ambiguous_numbers():
    entry = get_entry("stop_use_structure_levels")
    for raw in (2, -1, "maybe", None, []):
        accepted, _, message = parse_value(entry, raw)
        assert accepted is False
        assert message


@pytest.mark.parametrize(
    "value,expected",
    [
        ("*/1", True),
        ("*", False),
        ("6", True),
        ("*/6", True),
        ("0", False),
        ("abc", False),
        ("", False),
    ],
)
def test_schedule_hour_format_matches_the_scheduler_parser(value, expected):
    assert is_valid_schedule_hour(value) is expected


@pytest.mark.parametrize(
    "key",
    [
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
        "REDIS_HOST",
        "SENTRY_DSN",
        "METRICS_PORT",
        "metrics_enabled",
        "scheduler_db_path",
        "exchange_ledger_path",
        "ohlcv_store_path",
        "feature_store_path",
        "prediction_trace_dir",
        "min_data_points",
        "model_data_limits",
        "model_prediction_limit",
        "model_learning_enabled",
        "drift_alpha",
        "promotion_max_rmse_increase_ratio",
        "feature_store_min_rows",
        "prediction_trace_dir_backup",
        "ohlcv_store_max_rows_per_series",
        "model_auto_train_on_predict",
        "paper_fee_rate",
        "paper_slippage_rate",
        "exchange_request_timeout_ms",
        "exchange_reconcile_interval_seconds",
        "exchange_permission_cache_seconds",
    ],
)
def test_operator_only_keys_are_rejected(key):
    config = RecordingConfig()
    assert is_operator_only(key) is True
    ok, message = set_profile_value(config, key, "1")
    assert ok is False
    assert config.saved == {}


def test_unknown_keys_are_rejected():
    config = RecordingConfig()
    ok, message = set_profile_value(config, "not_a_setting", "1")
    assert ok is False
    assert config.saved == {}


def test_reset_restores_the_schema_default():
    config = RecordingConfig()
    ok, _ = set_profile_value(config, "risk_per_trade_pct", "3")
    assert ok is True
    ok, _ = set_profile_value(config, "risk_per_trade_pct", "1.0")
    assert ok is True
    assert config.config["risk_per_trade_pct"] == 1.0


def test_reset_stores_the_schema_default_again():
    config = RecordingConfig()
    ok, _ = set_profile_value(config, "risk_per_trade_pct", "3")
    assert ok is True
    ok, _ = reset_profile_value(config, "risk_per_trade_pct")
    assert ok is True
    assert config.config["risk_per_trade_pct"] == 1.0


def test_cost_model_values_are_stored_inside_the_cost_model_map():
    config = RecordingConfig()
    ok, _ = set_profile_value(config, "taker_fee_rate", "0.002")
    assert ok is True
    assert config.config["paper_cost_model"]["taker_fee_rate"] == 0.002
    assert config.config["paper_cost_model"]["maker_fee_rate"] == 0.001
    assert get_entry("taker_fee_rate").parent == "paper_cost_model"
