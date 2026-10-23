import os
import re
import sys

from loguru import logger

log_directory = "logs"
log_file = f"{log_directory}/app.log"

logger.remove()

_SECRET_PATTERN = re.compile(r"(auth_token|x_cg_demo_api_key|api_key|apikey)=[^&\s'\"]+")


def _redact_secrets(record):
    record["message"] = _SECRET_PATTERN.sub(r"\1=***", record["message"])


logger.configure(patcher=_redact_secrets)

log_format = os.getenv("LOG_FORMAT", "text").lower()
console_format = (
    "{message}"
    if log_format == "json"
    else "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

logger.add(sys.stdout, level="INFO", format=console_format, colorize=True)

logger.add(
    log_file,
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8",
    enqueue=True,
    backtrace=True,
    diagnose=True,
)

logger.info("Logger initialized.")
