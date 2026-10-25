import pytest

from common.exceptions import DataError, NetworkError, UpstreamUnavailableError
from config.logger import logger as configured_logger
from data.data_provider import _report_enrichment_failure
from data.sources.news_fetcher import _report_news_failure
from utils.circuit_breaker import CircuitBreakerError


@pytest.fixture
def captured():
    messages: list[tuple[str, str]] = []

    def sink(message):
        messages.append((message.record["level"].name, message.record["message"]))

    handler_id = configured_logger.add(sink, format="{message}", level="DEBUG")
    try:
        yield messages
    finally:
        configured_logger.remove(handler_id)


@pytest.mark.parametrize("exc", [UpstreamUnavailableError("down"), CircuitBreakerError("open")])
def test_enrichment_upstream_failures_are_not_errors(captured, exc):
    _report_enrichment_failure("Error fetching trending data", exc)

    assert [level for level, _ in captured] == ["DEBUG"]


@pytest.mark.parametrize("exc", [DataError("broken"), NetworkError("http 500")])
def test_enrichment_unexpected_failures_stay_errors(captured, exc):
    _report_enrichment_failure("Error fetching trending data", exc)

    assert [level for level, _ in captured] == ["ERROR"]


def test_news_upstream_failure_is_not_a_warning(captured):
    _report_news_failure(UpstreamUnavailableError("Upstream blocked access"))

    assert [level for level, _ in captured] == ["DEBUG"]


def test_news_unexpected_failure_stays_a_warning(captured):
    _report_news_failure(ValueError("malformed payload"))

    assert [level for level, _ in captured] == ["WARNING"]
