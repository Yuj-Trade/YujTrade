import pytest

from trading.exchanges.errors import ExchangeConfigError
from trading.exchanges.gate_inputs import load_exchange_settings, parse_bool


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("  false  ", False),
        (" True ", True),
    ],
)
def test_parse_bool_accepts_the_known_spellings(value, expected):
    assert parse_bool(value, "some_key") is expected


@pytest.mark.parametrize("value", [2, -1, "maybe", "", None, [], 1.0, {}, "2"])
def test_parse_bool_rejects_anything_else(value):
    with pytest.raises(ExchangeConfigError):
        parse_bool(value, "some_key")


def test_parse_bool_names_the_key_in_the_error():
    with pytest.raises(ExchangeConfigError) as excinfo:
        parse_bool("maybe", "exchange_live_enabled")
    assert "invalid_boolean:exchange_live_enabled" in str(excinfo.value)


class _Config:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


def test_a_string_false_never_enables_live():
    config = _Config({"exchange_live_enabled": "false"})
    settings = load_exchange_settings(config)
    assert settings.live_enabled is False


def test_a_string_false_for_sandbox_is_false_not_true():
    config = _Config({"exchange_sandbox": "false"})
    settings = load_exchange_settings(config)
    assert settings.sandbox is False


def test_an_invalid_boolean_is_an_error():
    config = _Config({"exchange_live_enabled": "maybe"})
    with pytest.raises(ExchangeConfigError):
        load_exchange_settings(config)


def test_default_config_still_parses_safely():
    settings = load_exchange_settings(_Config({}))
    assert settings.sandbox is True
    assert settings.shadow_mode is True
    assert settings.live_enabled is False


def test_a_comma_separated_enabled_string_is_split():
    config = _Config({"exchange_enabled": "binance,kraken"})
    settings = load_exchange_settings(config)
    assert settings.enabled == ("binance", "kraken")


def test_an_enabled_string_with_spaces_and_empty_segments_is_cleaned():
    config = _Config({"exchange_enabled": " binance , , kraken "})
    settings = load_exchange_settings(config)
    assert settings.enabled == ("binance", "kraken")


def test_an_unknown_exchange_in_the_enabled_list_is_an_error():
    config = _Config({"exchange_enabled": ["nosuch"]})
    with pytest.raises(ExchangeConfigError) as excinfo:
        load_exchange_settings(config)
    assert "unknown_exchange_in_config:nosuch" in str(excinfo.value)


def test_a_comma_separated_symbol_allowlist_is_split():
    config = _Config({"exchange_symbol_allowlist": "BTC/USDT,ETH/USDT"})
    settings = load_exchange_settings(config)
    assert settings.symbol_allowlist == ("BTC/USDT", "ETH/USDT")


def test_the_attested_keys_string_is_split():
    config = _Config({"exchange_attested_keys": "binance,kraken"})
    settings = load_exchange_settings(config)
    assert settings.attested_keys == ("binance", "kraken")


def test_build_exchange_service_returns_none_on_invalid_config():
    from services.trading_service import _build_exchange_service

    assert _build_exchange_service(_Config({"exchange_live_enabled": "maybe"})) is None
