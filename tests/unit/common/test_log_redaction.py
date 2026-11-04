import aiohttp
import yarl
from loguru import logger

from config.logger import logger as configured_logger


def _capture_sink(messages: list[str]):
    def sink(message):
        messages.append(message.record["message"])

    return sink


def test_auth_token_is_redacted_from_log_output():
    messages: list[str] = []
    handler_id = configured_logger.add(_capture_sink(messages), format="{message}", level="DEBUG")
    try:
        request_info = aiohttp.RequestInfo(
            url=yarl.URL("https://cryptopanic.com/api/v1/posts/"),
            method="GET",
            headers={},
            real_url=yarl.URL(
                "https://cryptopanic.com/api/v1/posts/?auth_token=FAKE_TOKEN_123&public=true"
            ),
        )
        exc = aiohttp.ClientResponseError(
            request_info=request_info,
            history=(),
            status=403,
            message="Forbidden",
        )
        configured_logger.warning(f"News fetch failed: {exc}")
    finally:
        configured_logger.remove(handler_id)

    captured = "\n".join(messages)
    assert "FAKE_TOKEN_123" not in captured
    assert "auth_token=***" in captured


def test_redaction_patcher_is_registered_on_shared_logger():
    assert logger is configured_logger


def test_telegram_token_in_the_exception_value_is_redacted():
    token = "8373302523:AAEDN-6lhfpYEuPjx6fU5c0yp0NKLeguxzQ"
    records: list[dict] = []

    def sink(message):
        records.append(message.record)

    handler_id = configured_logger.add(sink, format="{message}", level="DEBUG")
    try:
        try:
            raise ValueError("request failed")
        except ValueError as exc:
            exc.args = (f"https://api.telegram.org/bot{token}/getMe failed",)
            configured_logger.opt(exception=exc).error("startup failed")
    finally:
        configured_logger.remove(handler_id)

    record = records[-1]
    assert record["exception"] is not None
    assert token not in str(record["exception"].value)
    assert "bot***:***" in str(record["exception"].value)


def test_telegram_token_in_a_plain_message_is_redacted():
    messages: list[str] = []
    handler_id = configured_logger.add(_capture_sink(messages), format="{message}", level="DEBUG")
    token = "8373302523:AAEDN-6lhfpYEuPjx6fU5c0yp0NKLeguxzQ"
    try:
        configured_logger.warning(f"bot URL https://api.telegram.org/bot{token}/getMe")
    finally:
        configured_logger.remove(handler_id)

    captured = "\n".join(messages)
    assert token not in captured
    assert "bot***" in captured
