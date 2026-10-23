from loguru import logger

from config.logger import FILE_SINK_OPTIONS


def test_opt_exception_attaches_exception_to_record():
    records = []

    def sink(message):
        records.append(message.record)

    handler_id = logger.add(sink, format="{message}", level="DEBUG")
    try:
        try:
            raise ValueError("probe failure")
        except ValueError as exc:
            logger.opt(exception=exc).error("probe")
    finally:
        logger.remove(handler_id)

    assert records
    assert records[-1]["exception"] is not None
    assert records[-1]["exception"].type is ValueError


def test_file_sink_format_renders_exception():
    assert "{exception}" in FILE_SINK_OPTIONS["format"]


def test_file_sink_writes_traceback_to_disk(tmp_path):
    target = tmp_path / "trace.log"
    handler_id = logger.add(str(target), **FILE_SINK_OPTIONS)
    try:
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            logger.opt(exception=exc).error("probe")
    finally:
        logger.remove(handler_id)

    contents = target.read_text(encoding="utf-8")
    assert "Traceback" in contents
    assert "RuntimeError: boom" in contents


def test_traceback_starts_on_its_own_line(tmp_path):
    target = tmp_path / "sep.log"
    handler_id = logger.add(str(target), **FILE_SINK_OPTIONS)
    try:
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            logger.opt(exception=exc).error("MESSAGE_MARKER")
    finally:
        logger.remove(handler_id)

    contents = target.read_text(encoding="utf-8")
    assert "MESSAGE_MARKER\nTraceback" in contents
    assert "MESSAGE_MARKERTraceback" not in contents
