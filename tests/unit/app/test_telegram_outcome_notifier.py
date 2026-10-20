from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from app.telegram_bot import TelegramOutcomeNotifier
from application.outcome_ports import NotificationDeliveryError


def _notifier(error: Exception | None = None) -> TelegramOutcomeNotifier:
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=error) if error else AsyncMock()
    return TelegramOutcomeNotifier(bot, "123")


async def test_a_successful_send_reaches_the_admin():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    notifier = TelegramOutcomeNotifier(bot, "123")

    await notifier.send("TP hit")

    bot.send_message.assert_awaited_once_with(chat_id="123", text="TP hit")


@pytest.mark.parametrize("error", [RetryAfter(5), TimedOut(), NetworkError("down")])
async def test_a_retryable_error_is_mapped_to_a_retryable_delivery_error(error):
    notifier = _notifier(error)

    with pytest.raises(NotificationDeliveryError) as exc_info:
        await notifier.send("TP hit")

    assert exc_info.value.permanent is False


@pytest.mark.parametrize("error", [BadRequest("bad"), Forbidden("no")])
async def test_a_permanent_error_is_mapped_to_a_permanent_delivery_error(error):
    notifier = _notifier(error)

    with pytest.raises(NotificationDeliveryError) as exc_info:
        await notifier.send("TP hit")

    assert exc_info.value.permanent is True


async def test_a_bad_request_is_not_treated_as_a_network_error():
    assert issubclass(BadRequest, NetworkError)

    notifier = _notifier(BadRequest("bad"))

    with pytest.raises(NotificationDeliveryError) as exc_info:
        await notifier.send("TP hit")

    assert exc_info.value.permanent is True
