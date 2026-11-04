import asyncio
from unittest.mock import AsyncMock, MagicMock

from telegram.error import BadRequest, NetworkError, TimedOut

from app.telegram_bot import TelegramBotHandler


def _handler():
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.trading_service = MagicMock()
    handler.admin_chat_id = "123"
    return handler


def test_an_error_handler_is_registered():
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.application = MagicMock()

    handler._register_handlers()

    handler.application.add_error_handler.assert_called_once()


def test_start_survives_a_timed_out_reply():
    handler = _handler()
    update = MagicMock()
    update.message.reply_text = AsyncMock(side_effect=TimedOut("timed out"))
    context = MagicMock()

    handler._is_admin = AsyncMock(return_value=True)

    asyncio.run(handler.start(update, context))


def test_start_survives_a_network_error():
    handler = _handler()
    update = MagicMock()
    update.message.reply_text = AsyncMock(side_effect=NetworkError("network down"))
    context = MagicMock()

    handler._is_admin = AsyncMock(return_value=True)

    asyncio.run(handler.start(update, context))


async def _noop(update, context):
    raise TimedOut("timed out")


def test_the_error_handler_absorbs_a_timed_out_update():
    handler = _handler()
    handler._is_admin = AsyncMock(return_value=True)
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock(side_effect=TimedOut("timed out"))
    context = MagicMock()
    context.error = TimedOut("timed out")

    asyncio.run(handler.handle_error(update, context))


def test_the_error_handler_logs_a_bad_request_without_raising():
    handler = _handler()
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.error = BadRequest("bad request")

    asyncio.run(handler.handle_error(update, context))
