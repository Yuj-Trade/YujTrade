import asyncio
from typing import Any, List

from telegram import Bot

from utils.background_manager import BackgroundTaskManager
from config.settings import ConfigManager, SecretsManager
from config.logger import logger


class TaskServiceContainer:
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        raise RuntimeError("Call instance() instead")

    @classmethod
    async def instance(cls):
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls.__new__(cls)
                await cls._instance._initialize()
        return cls._instance

    async def _initialize(self):
        logger.info("Initializing TaskServiceContainer...")
        self.config_manager = ConfigManager()
        self.bot_token = SecretsManager.TELEGRAM_BOT_TOKEN
        self.background_tasks = BackgroundTaskManager()

        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured.")

        # همان Composition Root اصلی (شکاف ۱۸) — بدون graph موازی.
        from services.trading_service import create_trading_stack

        (
            self.config_manager,
            self.resource_manager,
            self.market_data_provider,
            self.trading_service,
        ) = await create_trading_stack(self.config_manager)

        logger.info("TaskServiceContainer initialized successfully.")

    async def cleanup(self):
        logger.info("Cleaning up TaskServiceContainer...")

        if self.background_tasks:
            await self.background_tasks.cancel_all()

        cleanup_tasks = []

        if hasattr(self, "trading_service") and self.trading_service:
            cleanup_tasks.append(self.trading_service.cleanup())

        if hasattr(self, "market_data_provider") and self.market_data_provider:
            cleanup_tasks.append(self.market_data_provider.close())

        if hasattr(self, "resource_manager") and self.resource_manager:
            cleanup_tasks.append(self.resource_manager.cleanup())

        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        logger.info("TaskServiceContainer cleaned up successfully.")


async def deliver_task_signals(
    bot_token: str, chat_id: int, signals: List[Any], summary_text: str
) -> int:
    """شکاف ۳۲ (وصل شد): تحویل نتایج task به تلگرام — همان chat_id که قبلاً
    فقط لاگ می‌شد. متن ساده (بدون ParseMode) تا escape لازم نباشد.
    تعداد پیام‌های ارسال‌شده برمی‌گردد؛ خطا منتشر می‌شود تا caller لاگ کند."""
    bot = Bot(token=bot_token)
    try:
        lines = [summary_text, f"Generated {len(signals)} signal(s)."]
        for sig in signals:
            symbol = getattr(sig, "symbol", "?")
            timeframe = getattr(sig, "timeframe", "?")
            sig_type = getattr(getattr(sig, "signal_type", ""), "value", "?")
            entry = getattr(sig, "entry_price", "?")
            conf = getattr(sig, "confidence_score", "?")
            lines.append(f"- {symbol} {timeframe} {sig_type}: entry {entry} (conf {conf})")
        await bot.send_message(chat_id=chat_id, text="\n".join(lines))
        return 1
    finally:
        try:
            await bot.shutdown()
        except Exception:
            pass


async def run_full_analysis_task(chat_id: int, message_id: int):
    try:
        logger.info(f"Task 'run_full_analysis_task' started for chat_id: {chat_id}")
        container = await TaskServiceContainer.instance()
        signals = await container.trading_service.run_analysis_for_all_symbols()
        logger.info(
            f"Task 'run_full_analysis_task' finished for chat_id: {chat_id}. "
            f"Generated {len(signals)} signals "
            f"({container.trading_service.last_errors} task error(s))."
        )
        # شکاف ۳۲: اتصال به مسیر تحویل — chat_id مصرف می‌شود.
        await deliver_task_signals(
            container.bot_token,
            chat_id,
            signals,
            "✅ Full Analyze completed.",
        )
        return signals
    except Exception as e:
        logger.error(f"Error in run_full_analysis_task: {e}", exc_info=True)
        return []


async def run_quick_scan_task(chat_id: int, message_id: int):
    try:
        logger.info(f"Task 'run_quick_scan_task' started for chat_id: {chat_id}")
        container = await TaskServiceContainer.instance()

        # تعریف واحد Quick Analysis (شکاف ۱۷) — همان implementation سرویس.
        signals = await container.trading_service.run_quick_analysis()
        logger.info(
            f"Task 'run_quick_scan_task' finished for chat_id: {chat_id}. "
            f"Generated {len(signals)} signals "
            f"({container.trading_service.last_errors} task error(s))."
        )
        # شکاف ۳۲: اتصال به مسیر تحویل — chat_id مصرف می‌شود.
        await deliver_task_signals(
            container.bot_token,
            chat_id,
            signals,
            "✅ Quick Scan completed.",
        )
        return signals
    except Exception as e:
        logger.error(f"Error in run_quick_scan_task: {e}", exc_info=True)
        return []
