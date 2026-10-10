import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.telegram_bot import TelegramBotHandler
from config.settings import ConfigManager


def test_risk_command_reports_config_manager_values(tmp_path):
    config_manager = ConfigManager(
        config_path=str(tmp_path / "config.json"),
        weights_path=str(tmp_path / "weights.json"),
    )
    config_manager.set("risk_per_trade_pct", 2.5)
    config_manager.set("max_portfolio_exposure_pct", 45.0)
    config_manager.set("max_concurrent_positions", 4)

    handler = TelegramBotHandler.__new__(TelegramBotHandler)
    handler.trading_service = MagicMock(name="TradingService")
    handler.config_manager = config_manager

    update = MagicMock(name="Update")
    update.message.reply_text = AsyncMock()
    context = MagicMock(name="Context")

    with patch.object(
        TelegramBotHandler, "_is_admin", AsyncMock(return_value=True)
    ):
        asyncio.run(handler.risk_command(update, context))

    update.message.reply_text.assert_awaited_once()
    text = str(update.message.reply_text.await_args.args[0])
    assert "2\\.5" in text
    assert "45\\.0" in text
    assert "4" in text
