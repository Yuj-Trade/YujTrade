import asyncio
from unittest.mock import AsyncMock, MagicMock

from loguru import logger as loguru_logger

from app.telegram_bot import TelegramBotHandler


def _handler(admin_chat_id: str):
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.admin_chat_id = admin_chat_id
    handler.trading_service = MagicMock()
    return handler


def _update(chat_id: int):
    update = MagicMock()
    update.effective_chat.id = chat_id
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    return update, context


def _capture(call):
    records: list[str] = []
    handler_id = loguru_logger.add(
        lambda m: records.append(m.record["message"]), format="{message}", level="DEBUG"
    )
    try:
        call()
    finally:
        loguru_logger.remove(handler_id)
    return records


def test_authorized_admin_is_granted_and_the_full_id_is_not_logged():
    secret = "1234567890"
    handler = _handler(secret)
    update, context = _update(1234567890)

    allowed = asyncio.run(handler._is_admin(update, context))

    assert allowed is True
    records = _capture(lambda: asyncio.run(handler._is_admin(update, context)))
    joined = "\n".join(records)
    assert secret not in joined


def test_unauthorized_chat_does_not_leak_the_expected_admin_id():
    admin = "9876543210"
    handler = _handler(admin)
    update, context = _update(1111111111)

    allowed = asyncio.run(handler._is_admin(update, context))

    assert allowed is False
    context.bot.send_message.assert_awaited_once()
    records = _capture(lambda: asyncio.run(handler._is_admin(update, context)))
    joined = "\n".join(records)
    assert admin not in joined


def test_an_odd_length_chat_id_does_not_raise():
    handler = _handler("123")
    update, context = _update(9)

    assert asyncio.run(handler._is_admin(update, context)) is False
