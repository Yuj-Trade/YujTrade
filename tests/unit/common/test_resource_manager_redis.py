import pytest
import redis.asyncio as redis

from config.logger import logger as configured_logger
from config.settings import SecretsManager
from utils.resource_manager import ResourceManager


class _FailingClient:
    def __init__(self):
        self.pings = 0
        self.closed = False

    async def ping(self):
        self.pings += 1
        raise redis.ConnectionError("Error 11001 connecting to redis.example:6379")

    async def aclose(self):
        self.closed = True


@pytest.fixture
def failing_redis(monkeypatch):
    client = _FailingClient()
    monkeypatch.setattr(SecretsManager, "REDIS_HOST", "redis.example")
    monkeypatch.setattr(SecretsManager, "REDIS_PORT", "6379")
    monkeypatch.setattr(SecretsManager, "REDIS_PASSWORD", "secret")
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: client)
    return client


async def test_failed_redis_connection_is_not_retried(failing_redis):
    manager = ResourceManager()

    messages: list[str] = []

    def sink(message):
        messages.append(message.record["message"])

    handler_id = configured_logger.add(sink, format="{message}", level="WARNING")
    try:
        assert await manager.get_redis_client() is None
        assert await manager.get_redis_client() is None
        assert await manager.get_redis_client() is None
    finally:
        configured_logger.remove(handler_id)

    assert failing_redis.pings == 1
    assert len([m for m in messages if "Redis connection error" in m]) == 1


async def test_cleanup_resets_the_unavailable_flag(failing_redis):
    manager = ResourceManager()
    assert await manager.get_redis_client() is None
    assert manager._redis_unavailable is True

    await manager.cleanup()
    assert manager._redis_unavailable is False


def _configure(monkeypatch, *, url="", ssl=False, username="default"):
    monkeypatch.setattr(SecretsManager, "REDIS_URL", url)
    monkeypatch.setattr(SecretsManager, "REDIS_HOST", "redis.example")
    monkeypatch.setattr(SecretsManager, "REDIS_PORT", 11880)
    monkeypatch.setattr(SecretsManager, "REDIS_USERNAME", username)
    monkeypatch.setattr(SecretsManager, "REDIS_SSL", ssl)
    monkeypatch.setattr(SecretsManager, "REDIS_PASSWORD", "secret")


def test_plain_scheme_is_used_when_tls_is_off(monkeypatch):
    _configure(monkeypatch, ssl=False)

    assert ResourceManager.build_redis_url() == ("redis://default:secret@redis.example:11880")


def test_tls_scheme_is_used_when_ssl_is_enabled(monkeypatch):
    _configure(monkeypatch, ssl=True)

    assert ResourceManager.build_redis_url() == ("rediss://default:secret@redis.example:11880")


def test_username_is_configurable(monkeypatch):
    _configure(monkeypatch, username="cache-user")

    assert ResourceManager.build_redis_url() == ("redis://cache-user:secret@redis.example:11880")


def test_blank_username_falls_back_to_default(monkeypatch):
    _configure(monkeypatch, username="")

    assert ResourceManager.build_redis_url() == ("redis://default:secret@redis.example:11880")


def test_explicit_url_overrides_the_assembled_parts(monkeypatch):
    _configure(monkeypatch, url="rediss://someone:pw@other.example:6379/2")

    assert ResourceManager.build_redis_url() == "rediss://someone:pw@other.example:6379/2"


def test_missing_password_disables_the_url(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(SecretsManager, "REDIS_PASSWORD", "")

    assert ResourceManager.build_redis_url() is None


def test_missing_host_disables_the_url(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(SecretsManager, "REDIS_HOST", "")

    assert ResourceManager.build_redis_url() is None


def test_redaction_hides_the_password_only():
    redacted = ResourceManager.redact_redis_url("rediss://default:supersecret@redis.example:11880")

    assert redacted == "rediss://default:****@redis.example:11880"
    assert "supersecret" not in redacted


def test_redaction_keeps_a_url_without_credentials_readable():
    assert ResourceManager.redact_redis_url("redis://localhost:6379") == ("redis://localhost:6379")


async def test_tls_options_are_only_passed_when_tls_is_enabled(monkeypatch):
    captured: dict[str, object] = {}

    class _Client:
        async def ping(self):
            return True

        async def aclose(self):
            return None

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Client()

    _configure(monkeypatch, ssl=False)
    monkeypatch.setattr(redis, "from_url", fake_from_url)
    manager = ResourceManager()

    assert await manager.get_redis_client() is not None
    assert "ssl_cert_reqs" not in captured["kwargs"]
    assert captured["url"].startswith("redis://")

    captured.clear()
    _configure(monkeypatch, ssl=True)
    manager = ResourceManager()

    assert await manager.get_redis_client() is not None
    assert captured["kwargs"]["ssl_cert_reqs"] is None
    assert captured["url"].startswith("rediss://")


async def test_successful_connection_is_logged_without_the_password(monkeypatch):
    messages: list[str] = []

    class _Client:
        async def ping(self):
            return True

        async def aclose(self):
            return None

    _configure(monkeypatch, ssl=True)
    monkeypatch.setattr(redis, "from_url", lambda *a, **k: _Client())
    manager = ResourceManager()

    handler_id = configured_logger.add(
        lambda m: messages.append(m.record["message"]), format="{message}", level="DEBUG"
    )
    try:
        assert await manager.get_redis_client() is not None
    finally:
        configured_logger.remove(handler_id)

    assert any("Connected to Redis successfully (TLS)" in m for m in messages)
    assert not any("secret" in m for m in messages)
