from loguru import logger

from config.logger import FILE_SINK_OPTIONS


def test_file_sink_options_disable_variable_capture():
    assert FILE_SINK_OPTIONS["diagnose"] is False
    assert FILE_SINK_OPTIONS["backtrace"] is True


def test_file_sink_does_not_leak_local_variables(tmp_path):
    target = tmp_path / "probe.log"
    handler_id = logger.add(str(target), **FILE_SINK_OPTIONS)
    try:

        def _raise_with_local():
            secret_value = "FAKE_LOCAL_987"
            raise RuntimeError(f"boom {len(secret_value)}")

        try:
            _raise_with_local()
        except RuntimeError:
            logger.opt(exception=True).error("probe")
    finally:
        logger.remove(handler_id)

    contents = target.read_text(encoding="utf-8")
    assert "probe" in contents
    assert "FAKE_LOCAL_987" not in contents
