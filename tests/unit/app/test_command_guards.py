import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram_bot import TelegramBotHandler


def _handler(trading_service):
    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.trading_service = trading_service
    handler.config_manager = MagicMock(name="ConfigManager")
    return handler


def _update_context(admin_replies=True):
    update = MagicMock(name="Update")
    update.message.reply_text = AsyncMock()
    context = MagicMock(name="Context")
    context.args = []
    return update, context


def test_signals_command_never_executes():
    trading_service = MagicMock(name="TradingService")
    signal = MagicMock(name="Signal")
    signal.symbol = "BTC/USDT"
    signal.timeframe = "1h"
    trading_service.run_quick_analysis = AsyncMock(return_value=[signal])
    trading_service.execute_signal = AsyncMock(return_value={"ok": True})
    handler = _handler(trading_service)
    handler.format_signal_message = MagicMock(return_value=["formatted"])
    update, context = _update_context()

    with patch.object(
        TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)
    ):
        asyncio.run(handler.signals_command(update, context))

    trading_service.run_quick_analysis.assert_awaited_once()
    trading_service.execute_signal.assert_not_called()
    update.message.reply_text.assert_awaited()


def test_paper_command_reports_accepted_and_rejected():
    for ok, word in ((True, "accepted"), (False, "rejected")):
        trading_service = MagicMock(name="TradingService")
        signal = MagicMock(name="Signal")
        signal.symbol = "BTC/USDT"
        signal.timeframe = "1h"
        trading_service.run_quick_analysis = AsyncMock(return_value=[signal])
        trading_service.execute_signal = AsyncMock(return_value={"ok": ok})
        handler = _handler(trading_service)
        update, context = _update_context()

        with patch.object(
            TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)
        ):
            asyncio.run(handler.paper_command(update, context))

        trading_service.execute_signal.assert_awaited_once()
        texts = [
            str(call.args[0])
            for call in update.message.reply_text.await_args_list
        ]
        assert any(word in text for text in texts)


def test_paper_command_rejects_non_admin():
    trading_service = MagicMock(name="TradingService")
    trading_service.run_quick_analysis = AsyncMock(return_value=[MagicMock()])
    trading_service.execute_signal = AsyncMock(return_value={"ok": True})
    handler = _handler(trading_service)
    update, context = _update_context()

    with patch.object(
        TelegramBotHandler, "_is_admin", AsyncMock(return_value=False)
    ):
        asyncio.run(handler.paper_command(update, context))

    trading_service.run_quick_analysis.assert_not_called()
    trading_service.execute_signal.assert_not_called()
