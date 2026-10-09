import asyncio
import warnings
from typing import List, Optional

import pandas as pd

from config.settings import ConfigManager
from common.constants import SYMBOLS, TIME_FRAMES
from config.logger import logger
from modeling.model_manager import ModelManager, ModelDataProvider
from data.data_provider import MarketDataProvider
from utils.resource_manager import ResourceManager

warnings.filterwarnings("ignore")


class TrainingDataProvider(ModelDataProvider):
    """A dedicated data provider for the training script.

    قرارداد واحد با TradingService.get_data_for_model (قاعده ۱۰):
    محدودیت‌ها فقط از Config خوانده می‌شوند؛ تفاوت صرفاً parameter است."""

    def __init__(
        self,
        market_data_provider: MarketDataProvider,
        config_manager: Optional[ConfigManager] = None,
    ):
        self._market_data_provider = market_data_provider
        self._config_manager = config_manager or ConfigManager()

    async def get_data_for_model(
        self, symbol: str, timeframe: str, for_prediction: bool = False
    ) -> Optional[pd.DataFrame]:
        limit_map = self._config_manager.get(
            "model_data_limits",
            {"1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300},
        )
        limit = limit_map.get(timeframe, 2000)
        if for_prediction:
            limit = min(
                limit, self._config_manager.get("model_prediction_limit", 300)
            )
        return await self._market_data_provider.fetch_ohlcv_data(
            symbol, timeframe, limit=limit
        )


class ModelTrainer:
    def __init__(
        self,
        config: ConfigManager,
        market_data_provider: MarketDataProvider,
        model_manager: ModelManager,
    ):
        self.config = config
        self.market_data_provider = market_data_provider
        self.model_manager = model_manager

    async def train_and_save_model(self, symbol: str, timeframe: str, model_type: str):
        logger.info(
            f"--- Starting training for {symbol}-{timeframe} ({model_type}) ---"
        )
        try:
            limit_map = self.config.get(
                "model_data_limits",
                {"1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300},
            )
            limit = limit_map.get(timeframe, 2000)

            data = await self.market_data_provider.fetch_ohlcv_data(
                symbol, timeframe, limit=limit
            )
            if data is None or data.empty or len(data) < 200:
                logger.warning(f"Insufficient data for {symbol}-{timeframe}. Skipping.")
                return

            # The model manager now uses the data provider passed to it,
            # so we just need to call its train_model method.
            is_trained = await self.model_manager.train_model(
                model_type, symbol, timeframe, data
            )

            if is_trained:
                logger.info(
                    f"✅ Successfully trained and saved {model_type} model for {symbol}-{timeframe}"
                )
            else:
                logger.error(
                    f"❌ Failed to train model for {symbol}-{timeframe} ({model_type})."
                )

        except Exception as e:
            logger.error(
                f"Error during training for {symbol}-{timeframe} ({model_type}): {e}",
                exc_info=True,
            )

    async def train_all_models(self):
        logger.info("Starting model training for all symbols and timeframes.")
        symbols: List[str] = self.config.get("symbols", SYMBOLS)
        timeframes: List[str] = self.config.get("timeframes", TIME_FRAMES)
        model_types = ["lstm", "xgboost"]

        tasks = []
        if symbols and timeframes:
            for symbol in symbols:
                for timeframe in timeframes:
                    for model_type in model_types:
                        tasks.append(
                            self.train_and_save_model(symbol, timeframe, model_type)
                        )

        await asyncio.gather(*tasks)
        logger.info("--- Model training process finished. ---")


async def main():
    config_manager = ConfigManager()
    resource_manager = ResourceManager()
    await resource_manager.get_session()
    await resource_manager.get_redis_client()

    market_data_provider = MarketDataProvider(
        resource_manager=resource_manager, config_manager=config_manager
    )
    await market_data_provider.initialize()

    training_data_provider = TrainingDataProvider(
        market_data_provider, config_manager
    )

    model_manager = ModelManager(
        data_provider=training_data_provider, model_path="models"
    )

    trainer = ModelTrainer(config_manager, market_data_provider, model_manager)
    await trainer.train_all_models()

    await market_data_provider.close()
    await model_manager.shutdown()
    await resource_manager.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Training process interrupted by user.")
    except Exception as e:
        logger.error(f"Fatal error in training script: {e}", exc_info=True)
