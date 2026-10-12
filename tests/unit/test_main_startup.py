import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import SecretsManager
from main import MainApp


def _stack(monkeypatch):
    config_manager = MagicMock()
    config_manager.get.side_effect = lambda key, default=None: default
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
    return service


@pytest.mark.parametrize(
    ("token", "admin"),
    [("", ""), ("token", ""), ("", "123")],
)
def test_missing_bot_credentials_exit_code_2_after_cleanup(monkeypatch, token, admin):
    service = _stack(monkeypatch)
    monkeypatch.setattr(SecretsManager, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(SecretsManager, "ADMIN_CHAT_ID", admin)
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(MainApp().run())
    assert exc_info.value.code == 2
    service.cleanup.assert_awaited_once()


def test_present_bot_credentials_start_without_exit_code(monkeypatch):
    _stack(monkeypatch)
    monkeypatch.setattr(SecretsManager, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(SecretsManager, "ADMIN_CHAT_ID", "123")
    handler = MagicMock()
    handler.application.initialize = AsyncMock()
    handler.application.start = AsyncMock()
    handler.application.updater.start_polling = AsyncMock()
    handler.application.updater.running = False
    monkeypatch.setattr("main.TelegramBotHandler", MagicMock(return_value=handler))
    app = MainApp()

    async def _run():
        task = asyncio.create_task(app.run())
        for _ in range(1000):
            if app.bot_handler is not None:
                break
            await asyncio.sleep(0.01)
        assert app.bot_handler is handler
        app.shutdown_event.set()
        await asyncio.wait_for(task, timeout=30)

    asyncio.run(_run())
