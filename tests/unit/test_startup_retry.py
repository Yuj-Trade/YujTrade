import asyncio
from unittest.mock import AsyncMock, MagicMock

from telegram.error import NetworkError, RetryAfter, TimedOut

from main import MainApp


def _app(initialize=None, start=None, polling=None):
    app = MainApp()
    app.bot_handler = MagicMock()
    application = MagicMock()
    application.initialize = AsyncMock(side_effect=initialize)
    application.start = AsyncMock(side_effect=start)
    application.updater = MagicMock()
    application.updater.start_polling = AsyncMock(side_effect=polling)
    app.bot_handler.application = application
    return app, application


def test_startup_retries_a_transient_timeout_then_succeeds(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimedOut("timed out")

    app, application = _app(initialize=flaky)

    asyncio.run(app._start_telegram_with_retry(attempts=4, base_delay=0.01))

    assert application.initialize.await_count == 3
    application.start.assert_awaited_once()
    application.updater.start_polling.assert_awaited_once()


def test_startup_honours_retry_after(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    attempts = {"n": 0}

    async def limited():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RetryAfter(retry_after=5)

    app, application = _app(initialize=limited)

    asyncio.run(app._start_telegram_with_retry(attempts=3, base_delay=0.01))

    assert application.initialize.await_count == 2
    sleep.assert_awaited()
    assert sleep.await_args_list[0].args[0] == 5.0


def test_startup_raises_a_clean_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    app, _application = _app(initialize=NetworkError("network down"))

    try:
        asyncio.run(app._start_telegram_with_retry(attempts=2, base_delay=0.01))
    except RuntimeError as exc:
        assert "could not start" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
