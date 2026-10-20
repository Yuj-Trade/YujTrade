import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.outcome_policy import PolicyError, build_policy
from common.constants import TIME_FRAMES
from config.settings import SecretsManager
from main import MainApp


class _FakeBackgroundManager:
    created: list[str] = []

    def create_task(self, coro, name=None):
        _FakeBackgroundManager.created.append(name)
        coro.close()
        return MagicMock()

    async def cancel_all(self):
        return None


def _stack(monkeypatch, config: dict | None = None):
    config_manager = MagicMock()
    config_manager.get.side_effect = lambda key, default=None: (
        config.get(key, default) if config else default
    )
    config_manager.config = config or {}
    resource_manager = MagicMock()
    resource_manager.cleanup = AsyncMock()
    provider = MagicMock()
    provider.close = AsyncMock()
    service = MagicMock()
    service.cleanup = AsyncMock()
    stack = (config_manager, resource_manager, provider, service)

    async def _create():
        return stack

    monkeypatch.setattr("services.trading_service.create_trading_stack", _create)
    monkeypatch.setattr("common.metrics.start_metrics_server", lambda **kwargs: False)
    monkeypatch.setattr("common.metrics.init_sentry", lambda dsn: False)
    return service, config_manager


def _handler() -> MagicMock:
    handler = MagicMock()
    handler.application.initialize = AsyncMock()
    handler.application.start = AsyncMock()
    handler.application.updater.start_polling = AsyncMock()
    handler.application.updater.running = False
    handler.admin_chat_id = "123"
    return handler


async def _run_app(app: MainApp) -> None:
    task = asyncio.create_task(app.run())
    for _ in range(1000):
        if app.bot_handler is not None:
            break
        await asyncio.sleep(0.01)
    app.shutdown_event.set()
    await asyncio.wait_for(task, timeout=30)


def _prepare(monkeypatch, config: dict | None = None):
    _FakeBackgroundManager.created = []
    monkeypatch.setattr("utils.background_manager.BackgroundTaskManager", _FakeBackgroundManager)
    service, config_manager = _stack(monkeypatch, config)
    monkeypatch.setattr(SecretsManager, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(SecretsManager, "ADMIN_CHAT_ID", "123")
    handler = _handler()
    monkeypatch.setattr("main.TelegramBotHandler", MagicMock(return_value=handler))
    return service, config_manager, handler


def test_the_off_mode_creates_no_outcome_watch_task(monkeypatch):
    service, _config_manager, handler = _prepare(monkeypatch, {"outcome_notifications_mode": "off"})
    app = MainApp()

    asyncio.run(_run_app(app))

    assert "OutcomeWatch" not in _FakeBackgroundManager.created
    assert app.bot_handler is handler


def test_an_invalid_configuration_disables_the_feature_without_stopping_the_bot(monkeypatch):
    service, _config_manager, handler = _prepare(
        monkeypatch, {"outcome_notifications_mode": "loud", "outcome_notifications_since": ""}
    )
    app = MainApp()

    asyncio.run(_run_app(app))

    assert "OutcomeWatch" not in _FakeBackgroundManager.created
    assert app.bot_handler is handler


def test_the_shadow_mode_creates_the_outcome_watch_task(monkeypatch):
    service, _config_manager, handler = _prepare(
        monkeypatch,
        {
            "outcome_notifications_mode": "shadow",
            "outcome_notifications_since": "2026-10-01T00:00:00+00:00",
        },
    )
    app = MainApp()

    asyncio.run(_run_app(app))

    assert "OutcomeWatch" in _FakeBackgroundManager.created
    assert app.bot_handler is handler


def test_the_policy_loader_falls_back_to_off():
    app = MainApp()
    config_manager = MagicMock()
    config_manager.config = {"outcome_notifications_mode": "loud"}

    policy = app._load_outcome_policy(config_manager)

    assert policy.mode == "off"
    assert policy.enabled is False


def test_the_policy_loader_keeps_a_valid_configuration():
    app = MainApp()
    config_manager = MagicMock()
    config_manager.config = {
        "outcome_notifications_mode": "shadow",
        "outcome_notifications_since": "2026-10-01T00:00:00+00:00",
    }

    policy = app._load_outcome_policy(config_manager)

    assert policy.mode == "shadow"
    assert policy.enabled is True


def test_a_live_mode_without_a_since_is_rejected_by_the_policy():
    with pytest.raises(PolicyError):
        build_policy(
            {"outcome_notifications_mode": "live", "outcome_notifications_since": ""},
            frozenset(TIME_FRAMES),
        )
