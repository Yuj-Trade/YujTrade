import json
from pathlib import Path

import pytest

from config.profile_keys import (
    ProfileKeyStore,
    ProfileKeyStoreError,
    exchange_secret_from_profile,
    get_store,
    provider_key_from_profile,
    set_store,
)
from config.settings import SecretsManager
from trading.exchanges.registry import get_spec
from utils.security import KeyEncryptor

PASSWORD = "unit-test-encryption-password"


@pytest.fixture
def encryptor(tmp_path, monkeypatch):
    buffer = KeyEncryptor.__new__(KeyEncryptor)
    buffer.fernet = KeyEncryptor(PASSWORD).fernet
    monkeypatch.setattr(SecretsManager, "active_encryptor", staticmethod(lambda: buffer))
    yield buffer
    monkeypatch.undo()


@pytest.fixture
def store(tmp_path, encryptor):
    instance = ProfileKeyStore(tmp_path / "runs" / "profile_keys.enc.json")
    set_store(instance)
    yield instance
    set_store(None)


def test_a_saved_key_round_trips_and_the_file_has_no_plaintext(store):
    secret_value = "super-secret-api-key-value"
    store.set_exchange_value("binance", "live", "api_key", secret_value)
    assert store.exchange_value("binance", "live", "api_key") == secret_value
    raw = Path(store.path).read_text(encoding="utf-8")
    assert secret_value not in raw
    assert "api_key" in json.loads(raw)["exchanges"]["binance"]["live"]
    assert "super-secret" not in raw


def test_the_store_file_is_valid_json_with_encrypted_tokens(store):
    store.set_provider_value("CRYPTOPANIC_KEY", "provider-secret")
    document = json.loads(Path(store.path).read_text(encoding="utf-8"))
    token = document["providers"]["CRYPTOPANIC_KEY"]
    assert isinstance(token, str)
    assert token != "provider-secret"
    assert store.provider_value("CRYPTOPANIC_KEY") == "provider-secret"


def test_saving_is_refused_without_an_encryptor(tmp_path, monkeypatch):
    monkeypatch.setattr(SecretsManager, "active_encryptor", staticmethod(lambda: None))
    store = ProfileKeyStore(tmp_path / "store.json")
    with pytest.raises(ProfileKeyStoreError):
        store.set_exchange_value("binance", "live", "api_key", "value")
    assert not Path(store.path).exists()


def test_deleting_a_key_removes_the_field_only(store):
    store.set_exchange_value("binance", "live", "api_key", "first")
    store.set_exchange_value("binance", "live", "api_secret", "second")
    store.delete_exchange_value("binance", "live", "api_key")
    assert store.exchange_value("binance", "live", "api_key") is None
    assert store.exchange_value("binance", "live", "api_secret") == "second"


def test_provider_delete_removes_the_entry(store):
    store.set_provider_value("COINGECKO_KEY", "value")
    store.delete_provider_value("COINGECKO_KEY")
    assert store.provider_value("COINGECKO_KEY") is None
    assert store.has_provider_value("COINGECKO_KEY") is False


def test_status_helpers_report_presence_without_values(store):
    assert store.has_exchange_value("binance", "sandbox", "api_key") is False
    store.set_exchange_value("binance", "sandbox", "api_key", "value")
    assert store.has_exchange_value("binance", "sandbox", "api_key") is True
    assert store.has_exchange_value("binance", "live", "api_key") is False


def test_a_missing_store_reports_absent_values(tmp_path, encryptor):
    store = ProfileKeyStore(tmp_path / "absent.json")
    assert store.available() is True
    assert store.exchange_value("binance", "live", "api_key") is None
    assert store.provider_value("MESSARI_API_KEY") is None


def test_a_corrupt_store_raises(tmp_path, encryptor):
    target = tmp_path / "corrupt.json"
    target.write_text("not json", encoding="utf-8")
    store = ProfileKeyStore(target)
    with pytest.raises(ProfileKeyStoreError):
        store.exchange_value("binance", "live", "api_key")


def test_exchange_secret_lookup_maps_environment_names(store):
    spec = get_spec("binance")
    sandbox_names = spec.secret_names(True)
    live_names = spec.secret_names(False)
    store.set_exchange_value("binance", "sandbox", "api_key", "sandbox-key")
    store.set_exchange_value("binance", "live", "api_secret", "live-secret")
    assert exchange_secret_from_profile(sandbox_names[0]) == "sandbox-key"
    assert exchange_secret_from_profile(live_names[1]) == "live-secret"
    assert exchange_secret_from_profile("UNKNOWN_API_KEY") is None


def test_passphrase_venues_map_their_third_field(store):
    spec = get_spec("okx")
    names = spec.secret_names(False)
    assert names[2] == "OKX_API_PASSPHRASE"
    store.set_exchange_value("okx", "live", "api_passphrase", "passphrase")
    assert exchange_secret_from_profile(names[2]) == "passphrase"


def test_provider_lookup_reads_the_store(store):
    store.set_provider_value("ALPHA_VANTAGE_KEY", "alpha")
    assert provider_key_from_profile("ALPHA_VANTAGE_KEY") == "alpha"
    assert provider_key_from_profile("SENTRY_DSN") is None


def test_get_store_returns_a_default_instance():
    set_store(None)
    try:
        assert isinstance(get_store(), ProfileKeyStore)
    finally:
        set_store(None)


def test_saving_does_not_write_secrets_into_the_config(tmp_path, store):
    from config.settings import ConfigManager

    config = ConfigManager(config_path=str(tmp_path / "config.json"))
    store.set_exchange_value("binance", "live", "api_key", "top-secret-key")
    config.set("exchange_attested_keys", [])
    document = json.loads(Path(config.config_path).read_text(encoding="utf-8"))
    assert "top-secret-key" not in json.dumps(document)


def test_credentials_prefer_the_profile_store(tmp_path, monkeypatch, encryptor):
    from trading.exchanges import credentials as credentials_module
    from trading.exchanges.registry import get_spec

    store = ProfileKeyStore(tmp_path / "keys.json")
    store.set_exchange_value("binance", "live", "api_key", "profile-key")
    store.set_exchange_value("binance", "live", "api_secret", "profile-secret")
    set_store(store)
    monkeypatch.setattr(
        credentials_module.SecretsManager,
        "get_exchange_secret",
        staticmethod(lambda name: "env-key"),
    )
    creds = credentials_module.load_exchange_credentials(get_spec("binance"), False)
    set_store(None)
    assert creds is not None
    assert creds.api_key == "profile-key"
    assert creds.api_secret == "profile-secret"


def test_credentials_fall_back_to_the_environment(monkeypatch):
    from trading.exchanges import credentials as credentials_module
    from trading.exchanges.registry import get_spec

    set_store(ProfileKeyStore("absent-profile-store.json"))
    monkeypatch.setattr(
        credentials_module.SecretsManager,
        "get_exchange_secret",
        staticmethod(lambda name: f"env-{name}"),
    )
    creds = credentials_module.load_exchange_credentials(get_spec("binance"), False)
    set_store(None)
    assert creds is not None
    assert creds.api_key == "env-BINANCE_API_KEY"


def test_plaintext_rule_of_credentials_usable_is_unchanged(monkeypatch):
    from trading.exchanges import credentials as credentials_module
    from trading.exchanges.registry import get_spec

    spec = get_spec("binance")
    monkeypatch.setattr(
        credentials_module, "find_plaintext_exchange_secrets", lambda *_: ["BINANCE_API_KEY"]
    )
    monkeypatch.setattr(credentials_module, "load_exchange_credentials", lambda *_: None)
    usable, _ = credentials_module.credentials_usable(spec, False)
    assert usable is False
