from typing import Any

from config.logger import logger


class ExchangeConfigError(Exception):
    pass


class OurbitNotReady(ExchangeConfigError):
    pass


def sanitize(text: str, secrets: list[str]) -> str:
    cleaned = str(text)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        cleaned = cleaned.replace(secret, "***")
    return cleaned


def sanitize_against(text: str, values: list[Any]) -> str:
    return sanitize(text, [str(value) for value in values if value])


def log_exchange_error(context: str, exc: BaseException, secrets: list[str]) -> None:
    logger.error(f"{context}: {sanitize_against(exc, secrets)}")
