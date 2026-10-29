import base64

import pytest

from config.settings import SecretsManager
from trading.exchanges.credentials import (
    ExchangeCredentials,
    credentials_usable,
    find_plaintext_exchange_secrets,
    load_exchange_credentials,
)
from trading.exchanges.errors import ExchangeConfigError, OurbitNotReady, sanitize
from trading.exchanges.registry import get_spec


class FakeEncryptor:
    prefix = "enc:"

    def encrypt(self, data: str) -> str:
        return self.prefix + base64.b64encode(data.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        if not token.startswith(self.prefix):
            return ""
        return base64.b64decode(token[len(self.prefix) :]).decode("utf-8")


@pytest.fixture
def env(monkeypatch):
    store: dict[str, str] = {}

    def fake_config(name, default=None, cast=None):
        value = store.get(name, default)
        return value

    def fake_get_exchange_secret(name):
        encryptor = SecretsManager._encryptor
        if encryptor is None:
            return None
        value = store.get(f"ENCRYPTED_{name}", "")
        if not value:
            return None
        decrypted = encryptor.decrypt(value)
        return decrypted or None

    import trading.exchanges.credentials as credentials_module

    monkeypatch.setattr(credentials_module, "decouple_config", fake_config)
    monkeypatch.setattr(SecretsManager, "_encryptor", FakeEncryptor())
    monkeypatch.setattr(
        SecretsManager, "get_exchange_secret", staticmethod(fake_get_exchange_secret)
    )
    return store


def _store_encrypted(store, encryptor, name, value):
    store[f"ENCRYPTED_{name}"] = encryptor.encrypt(value)


def test_roundtrip_plain_value(env):
    encryptor = SecretsManager._encryptor
    spec = get_spec("binance")
    _store_encrypted(env, encryptor, "BINANCE_SANDBOX_API_KEY", "key-123")
    _store_encrypted(env, encryptor, "BINANCE_SANDBOX_API_SECRET", "secret-456")
    credentials = load_exchange_credentials(spec, sandbox=True)
    assert credentials == ExchangeCredentials(api_key="key-123", api_secret="secret-456")


def test_roundtrip_base64_multiline_value(env):
    encryptor = SecretsManager._encryptor
    spec = get_spec("coinbase")
    pem = "-----BEGIN PRIVATE KEY-----\nline1\nline2\n-----END PRIVATE KEY-----\n"
    encoded = base64.b64encode(pem.encode("utf-8")).decode("ascii")
    encoded_key = base64.b64encode(b"coinbase-key").decode("ascii")
    _store_encrypted(env, encryptor, "COINBASE_API_KEY", encoded_key)
    _store_encrypted(env, encryptor, "COINBASE_API_SECRET", encoded)
    credentials = load_exchange_credentials(spec, sandbox=False)
    assert credentials is not None
    assert credentials.api_key == "coinbase-key"
    assert credentials.api_secret == pem


def test_passphrase_required_venue(env):
    encryptor = SecretsManager._encryptor
    spec = get_spec("okx")
    _store_encrypted(env, encryptor, "OKX_API_KEY", "k")
    _store_encrypted(env, encryptor, "OKX_API_SECRET", "s")
    assert load_exchange_credentials(spec, sandbox=False) is None
    _store_encrypted(env, encryptor, "OKX_API_PASSPHRASE", "p")
    credentials = load_exchange_credentials(spec, sandbox=False)
    assert credentials is not None
    assert credentials.passphrase == "p"


def test_no_plaintext_fallback(env):
    spec = get_spec("binance")
    env["BINANCE_SANDBOX_API_KEY"] = "plain-key"
    env["BINANCE_SANDBOX_API_SECRET"] = "plain-secret"
    assert load_exchange_credentials(spec, sandbox=True) is None


def test_find_plaintext_reports_names_not_values(env):
    spec = get_spec("kraken")
    env["KRAKEN_API_KEY"] = "leaky-value"
    found = find_plaintext_exchange_secrets(spec, sandbox=False)
    assert found == ["KRAKEN_API_KEY"]
    assert "leaky-value" not in " ".join(found)


def test_plaintext_encrypted_pair_is_not_reported(env):
    encryptor = SecretsManager._encryptor
    spec = get_spec("kraken")
    _store_encrypted(env, encryptor, "KRAKEN_API_KEY", "v")
    assert find_plaintext_exchange_secrets(spec, sandbox=False) == []


def test_invalid_base64_disables_credentials(env):
    encryptor = SecretsManager._encryptor
    spec = get_spec("bullish")
    _store_encrypted(env, encryptor, "BULLISH_API_KEY", "not-valid-base64!!")
    _store_encrypted(env, encryptor, "BULLISH_API_SECRET", "also!!")
    assert load_exchange_credentials(spec, sandbox=False) is None


def test_credentials_unusable_when_plaintext_present(env):
    spec = get_spec("binance")
    env["BINANCE_SANDBOX_API_KEY"] = "plain-key"
    usable, secrets = credentials_usable(spec, sandbox=True)
    assert usable is False
    assert secrets == []


def test_credentials_usable_with_encrypted_values(env):
    encryptor = SecretsManager._encryptor
    spec = get_spec("binance")
    _store_encrypted(env, encryptor, "BINANCE_SANDBOX_API_KEY", "k")
    _store_encrypted(env, encryptor, "BINANCE_SANDBOX_API_SECRET", "s")
    usable, secrets = credentials_usable(spec, sandbox=True)
    assert usable is True
    assert secrets == ["k", "s", ""]


def test_sanitize_removes_every_secret():
    text = "error with key-123 and secret-456 and pass-789"
    cleaned = sanitize(text, ["key-123", "secret-456", "pass-789"])
    assert cleaned == "error with *** and *** and ***"


def test_sanitize_ignores_empty_secret():
    assert sanitize("value", ["", "value"]) == "***"


def test_sanitize_handles_overlapping_secrets():
    assert sanitize("abcd", ["abc", "abcd"]) == "***"


def test_exchange_config_error_hierarchy():
    assert issubclass(OurbitNotReady, ExchangeConfigError)
    assert issubclass(ExchangeConfigError, Exception)


def test_secret_value_never_reaches_a_log(env):
    from loguru import logger

    spec = get_spec("binance")
    env["BINANCE_API_KEY"] = "PLAINTEXT_LEAK_VALUE"
    env["BINANCE_API_SECRET"] = "PLAINTEXT_LEAK_SECRET"

    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        credentials_usable(spec, sandbox=False)
        logger.error("Decryption failed for api_key=PLAINTEXT_LEAK_VALUE in binance")
    finally:
        logger.remove(handler_id)

    captured = "\n".join(messages)
    assert "PLAINTEXT_LEAK_VALUE" not in captured
    assert "PLAINTEXT_LEAK_SECRET" not in captured
    assert "BINANCE_API_KEY" in captured


def test_encrypted_secret_value_never_reaches_a_log(env):
    from loguru import logger

    encryptor = SecretsManager._encryptor
    spec = get_spec("binance")
    _store_encrypted(env, encryptor, "BINANCE_SANDBOX_API_KEY", "ENCRYPTED_LEAK_VALUE")
    _store_encrypted(env, encryptor, "BINANCE_SANDBOX_API_SECRET", "ENCRYPTED_LEAK_SECRET")

    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        usable, secrets = credentials_usable(spec, sandbox=True)
        assert usable is True
        logger.error("submission failed: api_secret=" + ",".join(secrets))
    finally:
        logger.remove(handler_id)

    captured = "\n".join(messages)
    assert "ENCRYPTED_LEAK_VALUE" not in captured
    assert "ENCRYPTED_LEAK_SECRET" not in captured
