import json
from pathlib import Path
from typing import Any, Dict, Optional

from decouple import config as decouple_config

from common.constants import (
    SYMBOLS,
    TIME_FRAMES,
    AnalysisComponent,
)
from config.logger import logger
from utils.security import KeyEncryptor, get_password_from_key_manager


class SecretsManager:
    ENCRYPTION_PASSWORD = get_password_from_key_manager()

    _encryptor = None
    if ENCRYPTION_PASSWORD:
        try:
            _encryptor = KeyEncryptor(ENCRYPTION_PASSWORD)
        except Exception:
            logger.critical(
                "Failed to create encryptor. Check your SECRET_ENCRYPTION_PASSWORD "
                "or mounted secret."
            )
            _encryptor = None

    @staticmethod
    def get_secret(key: str, cast: type = str, default: Any = None) -> Optional[Any]:
        encrypted_key = f"ENCRYPTED_{key}"
        value = decouple_config(encrypted_key, default=None)
        if value and SecretsManager._encryptor:
            decrypted = SecretsManager._encryptor.decrypt(value)
            if not decrypted:
                logger.error(f"Failed to decrypt {key}. Please re-encrypt your keys.")
                return default
            try:
                return cast(decrypted)
            except (ValueError, TypeError):
                logger.error(f"Failed to cast decrypted key {key} to {cast}.")
                return default

        return decouple_config(key, default=default, cast=cast)

    TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", default="")
    ADMIN_CHAT_ID = get_secret("ADMIN_CHAT_ID", default="")
    CRYPTOPANIC_KEY = get_secret("CRYPTOPANIC_KEY", default="")
    ALPHA_VANTAGE_KEY = get_secret("ALPHA_VANTAGE_KEY", default="")
    COINGECKO_KEY = get_secret("COINGECKO_KEY", default="")
    COINDESK_API_KEY = get_secret("COINDESK_API_KEY", default="")
    MESSARI_API_KEY = get_secret("MESSARI_API_KEY", default="")
    SENTRY_DSN = get_secret("SENTRY_DSN", default="")

    TF_CPP_MIN_LOG_LEVEL = decouple_config("TF_CPP_MIN_LOG_LEVEL", default="3")
    TF_ENABLE_ONEDNN_OPTS = decouple_config("TF_ENABLE_ONEDNN_OPTS", default="0")

    # قاعده ۳۹: هیچ هاست/پورت پیش‌فرض embedded وجود ندارد (مشابه قاعده ۲۷
    # برای secret). در نبود REDIS_HOST/REDIS_PORT/REDIS_TOKEN، کش غیرفعال
    # است (ResourceManager.get_redis_client → None). مقداردهی این فیلدها
    # فقط از محیط/فایل .env انجام می‌شود.
    REDIS_HOST = decouple_config("REDIS_HOST", default="")
    REDIS_PORT = decouple_config("REDIS_PORT", default=6379, cast=int)
    REDIS_PASSWORD = get_secret("REDIS_TOKEN", default="")
    if not REDIS_PASSWORD:
        logger.warning(
            "REDIS_TOKEN is not set. Caching will be disabled; "
            "no default secret is embedded (قاعده ۲۷)."
        )


class ConfigManager:
    DEFAULT_CONFIG = {
        "symbols": SYMBOLS,
        "timeframes": TIME_FRAMES,
        "signal_threshold": 50,
        "max_signals_per_timeframe": 1,
        "enable_scheduled_analysis": False,
        "schedule_hour": "*/1",
        "app_version": "6.0.0",
        "timeframe_based_weights": True,
        # قرارداد واحد داده مدل (قاعده ۱۰): هم Training و هم Prediction
        # محدودیت‌ها را فقط از همین‌جا می‌خوانند.
        "model_data_limits": {
            "1h": 2000,
            "4h": 1500,
            "1d": 1000,
            "1w": 500,
            "1M": 300,
        },
        "model_prediction_limit": 300,
        "model_auto_train_on_predict": False,
        "metrics_enabled": False,
        "METRICS_PORT": 9108,
        "scheduler_db_path": "runs/scheduler.db",
    }

    DEFAULT_WEIGHTS_CONFIG = {
        "cache_config": {
            "default_ttl": 3600,
            "ohlcv": {"1h": 300, "4h": 900, "1d": 1800, "1w": 3600, "1M": 7200},
            "derivatives": 300,
            "macro": 86400,
            "indices": 600,
            "news": 600,
            "fundamental": 43200,
            "trending": 3600,
            "generic": 86400,
        }
    }

    def __init__(
        self,
        config_path: str = "config.json",
        weights_path: str = "indicator_weights.json",
    ):
        self.config_path = Path(config_path)
        self.weights_path = Path(weights_path)
        self.config = self._load_config()
        self.weights_config = self._load_weights_config()

    def _load_json_file(self, path: Path, default: Dict = None) -> Dict:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error loading {path}: {e}. Using defaults.")
        return default or {}

    def _load_config(self) -> Dict[str, Any]:
        loaded_config = self._load_json_file(self.config_path)
        return {**self.DEFAULT_CONFIG, **loaded_config}

    def _load_weights_config(self) -> Dict[str, Any]:
        loaded_weights = self._load_json_file(self.weights_path)
        if "cache_config" in loaded_weights:
            for key, value in self.DEFAULT_WEIGHTS_CONFIG["cache_config"].items():
                if key not in loaded_weights["cache_config"]:
                    loaded_weights["cache_config"][key] = value
        else:
            loaded_weights["cache_config"] = self.DEFAULT_WEIGHTS_CONFIG["cache_config"]
        return loaded_weights

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value
        self.save_config()

    def get_component_weights(self, timeframe: str) -> Dict[str, float]:
        if self.get("timeframe_based_weights", True):
            timeframe_weights = self.weights_config.get(
                "timeframe_based_settings", {}
            ).get(timeframe, {})
            if "component_weights" in timeframe_weights:
                return timeframe_weights["component_weights"]

        return self.weights_config.get("default_settings", {}).get(
            "component_weights",
            {
                AnalysisComponent.TECHNICAL_ANALYSIS.value: 40,
                AnalysisComponent.MARKET_CONTEXT.value: 25,
                AnalysisComponent.EXTERNAL_DATA.value: 15,
                AnalysisComponent.ML_MODELS.value: 20,
            },
        )

    def get_indicator_weights(self, timeframe: str) -> Dict[str, float]:
        if self.get("timeframe_based_weights", True):
            timeframe_weights = self.weights_config.get(
                "timeframe_based_settings", {}
            ).get(timeframe, {})
            if "indicator_weights" in timeframe_weights:
                return timeframe_weights["indicator_weights"]

        return self.weights_config.get("default_settings", {}).get(
            "indicator_weights", {}
        )

    def get_cache_config(self) -> Dict[str, Any]:
        return self.weights_config.get(
            "cache_config", self.DEFAULT_WEIGHTS_CONFIG["cache_config"]
        )

    def get_cache_ttl(self, category: str, sub_category: Optional[str] = None) -> int:
        cache_config = self.get_cache_config()
        category_config = cache_config.get(category)

        if isinstance(category_config, dict) and sub_category:
            return category_config.get(
                sub_category, cache_config.get("default_ttl", 3600)
            )
        elif isinstance(category_config, int):
            return category_config
        else:
            return cache_config.get("default_ttl", 3600)