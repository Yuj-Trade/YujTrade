import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_send_signals_retries_a_timed_out_send_and_delivers():
    handler = _handler()
    handler.application = MagicMock()
    handler.application.bot.send_message = AsyncMock(
        side_effect=[TimedOut("timed out"), None, None, None, None]
    )
    handler.format_signal_message = MagicMock(return_value=["message"])

    with patch("app.telegram_bot.asyncio.sleep", new=AsyncMock()):
        asyncio.run(
            handler.send_signals_to_telegram(
                [MagicMock()],
                "123",
                "summary",
                "no signals",
            )
        )

    assert handler.application.bot.send_message.await_count == 3


def test_send_signals_gives_up_after_persistent_timeouts_without_raising():
    handler = _handler()
    handler.application = MagicMock()
    handler.application.bot.send_message = AsyncMock(side_effect=TimedOut("timed out"))
    handler.format_signal_message = MagicMock(return_value=["message"])

    with patch("app.telegram_bot.asyncio.sleep", new=AsyncMock()):
        asyncio.run(
            handler.send_signals_to_telegram(
                [MagicMock()],
                "123",
                "summary",
                "no signals",
            )
        )

    assert handler.application.bot.send_message.await_count == 6


def test_send_signals_reports_failure_when_no_signals_text_never_delivers():
    handler = _handler()
    handler.application = MagicMock()
    handler.application.bot.send_message = AsyncMock(side_effect=NetworkError("down"))

    with patch("app.telegram_bot.asyncio.sleep", new=AsyncMock()):
        result = asyncio.run(handler._send_message_with_retry("123", "hello"))

    assert result is False
    assert handler.application.bot.send_message.await_count == 3
