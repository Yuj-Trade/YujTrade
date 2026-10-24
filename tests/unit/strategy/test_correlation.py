from loguru import logger

from analysis.correlation import IndicatorCorrelationManager


def test_no_history_is_silent_debug_not_warning():
    manager = IndicatorCorrelationManager()
    warnings: list[str] = []
    debug: list[str] = []

    def sink(message):
        record = message.record
        if record["level"].name == "WARNING":
            warnings.append(record["message"])
        elif record["level"].name == "DEBUG":
            debug.append(record["message"])

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        manager.compute_correlations({"rsi": {"result": 1}}, None)
    finally:
        logger.remove(handler_id)

    assert warnings == []
    assert any("decorrelation_disabled" in m for m in debug)
