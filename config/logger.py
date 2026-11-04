import os
import re
import sys

from loguru import logger

log_directory = "logs"
log_file = f"{log_directory}/app.log"

logger.remove()

_SECRET_PATTERN = re.compile(
    r"(auth_token|x_cg_demo_api_key|api_key|apikey|api_secret|secret|passphrase|password"
    r"|encrypted_[a-z0-9_]+)=[^&\s'\"]+",
    re.IGNORECASE,
)

_TELEGRAM_TOKEN_PATTERN = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{30,}")


def _redact_text(text: str) -> str:
    text = _SECRET_PATTERN.sub(r"\1=***", text)
    return _TELEGRAM_TOKEN_PATTERN.sub("bot***:***", text)


def _redact_secrets(record):
    record["message"] = _redact_text(record["message"])
    exception = record.get("exception")
    if exception is None:
        return
    value = exception.value
    try:
        raw = str(value)
    except (TypeError, ValueError):
        return
    redacted = _redact_text(raw)
    if redacted != raw:
        try:
            exception.value.args = (redacted,)
        except (AttributeError, TypeError):
            pass


logger.configure(patcher=_redact_secrets)

log_format = os.getenv("LOG_FORMAT", "text").lower()
console_format = (
    "{message}"
    if log_format == "json"
    else "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

logger.add(sys.stdout, level="INFO", format=console_format, colorize=True)

FILE_SINK_OPTIONS = dict(
    format=(
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | "
        "{message}\n{exception}"
    ),
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8",
    enqueue=True,
    backtrace=True,
    diagnose=False,
)

logger.add(log_file, **FILE_SINK_OPTIONS)

logger.info("Logger initialized.")
