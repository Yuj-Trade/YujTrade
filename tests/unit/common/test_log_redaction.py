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
