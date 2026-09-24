import asyncio
import signal
import sys

from services.trading_service import TradingService
from config.settings import SecretsManager
from config.logger import logger
from utils.resource_manager import ResourceManager
from app.telegram_bot import TelegramBotHandler


class MainApp:
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.resource_manager: ResourceManager | None = None
        self.trading_service: TradingService | None = None
        self.bot_handler: TelegramBotHandler | None = None
        self.background_tasks_manager = None

    def _handle_shutdown(self, sig, frame):
        if not self.shutdown_event.is_set():
            logger.info(f"Shutdown signal {sig} received. Initiating graceful shutdown...")
            self.shutdown_event.set()

    @staticmethod
    def _parse_schedule_hour(value) -> float:
        """schedule_hour با قالب "*/N" یعنی هر N ساعت؛ عدد ساده هم ساعت است.
        خروجی ثانیه؛ نامعتبر → پیش‌فرض ۱ ساعت."""
        try:
            text = str(value).strip()
            if text.startswith("*/"):
                hours = float(text[2:])
            else:
                hours = float(text)
            if hours <= 0:
                raise ValueError
            return hours * 3600.0
        except (TypeError, ValueError):
            logger.warning(
                f"Invalid schedule_hour={value!r}, falling back to 1 hour."
            )
            return 3600.0

    async def _scheduled_analysis_loop(self, config_manager):
        interval = self._parse_schedule_hour(
            config_manager.get("schedule_hour", "*/1")
        )
        logger.info(
            f"Scheduled analysis enabled every {interval / 3600:.2f}h."
        )
        while not self.shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self.shutdown_event.wait(), timeout=interval
                )
            except asyncio.TimeoutError:
                pass
            if self.shutdown_event.is_set():
                break
            try:
                await self.bot_handler.run_scheduled_analysis()
            except Exception as e:
                logger.error(f"Scheduled analysis failed: {e}", exc_info=True)

    async def run(self):
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        try:
            logger.info("Initializing application components...")
            # همان Composition Root اصلی (شکاف ۱۸) — بدون graph موازی.
            from services.trading_service import create_trading_stack

            (
                config_manager,
                self.resource_manager,
                self.market_data_provider,
                self.trading_service,
            ) = await create_trading_stack()
            logger.info(
                f"YujTrade v{config_manager.get('app_version', '?')} initialized."
            )

            bot_token = SecretsManager.TELEGRAM_BOT_TOKEN
            if not bot_token:
                logger.error("TELEGRAM_BOT_TOKEN is not configured. Cannot start bot.")
            
            from utils.background_manager import BackgroundTaskManager
            self.background_tasks_manager = BackgroundTaskManager()

            admin_chat_id = SecretsManager.ADMIN_CHAT_ID
            if not admin_chat_id:
                logger.critical("CRITICAL: ADMIN_CHAT_ID is not configured. Bot interactions will be limited.")

            if bot_token and admin_chat_id:
                logger.info("Initializing Telegram bot handler...")
                self.bot_handler = TelegramBotHandler(
                    bot_token=bot_token,
                    admin_chat_id=admin_chat_id,
                    config_manager=config_manager,
                    trading_service=self.trading_service,
                    background_tasks=self.background_tasks_manager,
                )

                logger.info("Starting Telegram bot...")
                
                await self.bot_handler.application.initialize()
                
                await self.bot_handler.application.start()
                await self.bot_handler.application.updater.start_polling()
                
                logger.info("Telegram bot started successfully.")

                # اجرای دوره‌ای تحلیل با مکانیزم موجود (شکاف ۱۹):
                # BackgroundTaskManager + run_scheduled_analysis، بدون Scheduler جدید.
                if config_manager.get("enable_scheduled_analysis", False):
                    self.background_tasks_manager.create_task(
                        self._scheduled_analysis_loop(config_manager),
                        name="ScheduledAnalysis",
                    )
            else:
                logger.warning("Telegram bot not started due to missing token or admin chat ID.")

            await self.shutdown_event.wait()

        except asyncio.TimeoutError as e:
            logger.error(f"A component timed out during initialization: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error during application run: {e}", exc_info=True)
        finally:
            logger.info("Shutdown event set. Cleaning up resources...")
            
            if self.bot_handler and self.bot_handler.application and hasattr(self.bot_handler.application, 'updater') and self.bot_handler.application.updater.running:
                try:
                    await self.bot_handler.application.updater.stop()
                    await self.bot_handler.application.stop()
                    await self.bot_handler.application.shutdown()
                except Exception as e:
                    logger.error(f"Error stopping bot: {e}")

            if self.background_tasks_manager:
                await self.background_tasks_manager.cancel_all()

            if self.trading_service:
                try:
                    await self.trading_service.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up trading service: {e}")

            if getattr(self, "market_data_provider", None):
                try:
                    await self.market_data_provider.close()
                except Exception as e:
                    logger.error(f"Error closing market data provider: {e}")
                    
            if self.resource_manager:
                try:
                    await self.resource_manager.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up resource manager: {e}")
                    
            logger.info("Application has been shut down gracefully.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = MainApp()
    try:
        asyncio.run(app.run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application interrupted by user. Shutting down.")