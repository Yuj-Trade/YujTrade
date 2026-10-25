from data.source_health import SourceHealthMonitor, SourceStatus


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def _monitor(cooldown=60.0):
    clock = Clock()
    return SourceHealthMonitor(clock=clock, cooldown_seconds=cooldown), clock


def test_unknown_source_is_healthy():
    monitor, _ = _monitor()

    assert monitor.is_healthy("never-seen") is True


def test_register_is_idempotent():
    monitor, _ = _monitor()

    monitor.register("binance")
    monitor.register("binance")

    assert list(monitor.snapshot()) == ["binance"]


def test_record_success_updates_the_status():
    monitor, _ = _monitor()

    monitor.record_success("binance", latency_ms=12.5)

    status = monitor.snapshot()["binance"]
    assert status == {
        "ok": True,
        "latency_ms": 12.5,
        "last_error": "",
        "success": 1,
        "fail": 0,
    }


def test_record_failure_keeps_the_source_healthy_below_the_threshold():
    monitor, _ = _monitor()

    for _ in range(4):
        monitor.record_failure("binance", "timeout")

    assert monitor.is_healthy("binance") is True
    assert monitor.snapshot()["binance"]["fail"] == 4


def test_five_failures_without_success_mark_the_source_unhealthy():
    monitor, _ = _monitor()

    for _ in range(5):
        monitor.record_failure("binance", "timeout")

    assert monitor.is_healthy("binance") is False


def test_ten_failures_mark_the_source_unhealthy_even_after_a_success():
    monitor, _ = _monitor()
    monitor.record_success("binance")

    for _ in range(10):
        monitor.record_failure("binance", "timeout")

    assert monitor.is_healthy("binance") is False


def test_error_text_is_truncated():
    monitor, _ = _monitor()

    monitor.record_failure("binance", "x" * 500)

    assert len(monitor.snapshot()["binance"]["last_error"]) == 300


def test_source_becomes_healthy_again_after_the_cooldown():
    monitor, clock = _monitor(cooldown=60.0)
    for _ in range(5):
        monitor.record_failure("binance")
    assert monitor.is_healthy("binance") is False

    clock.now += 61

    assert monitor.is_healthy("binance") is True


def test_cooldown_doubles_on_repeated_failures():
    monitor, clock = _monitor(cooldown=60.0)
    for _ in range(5):
        monitor.record_failure("binance")
    first_deadline = monitor._cooldowns["binance"]

    monitor.record_failure("binance")

    assert monitor._cooldowns["binance"] == first_deadline * 2


def test_cooldown_is_capped_at_one_hour():
    monitor, _ = _monitor(cooldown=600.0)
    for _ in range(5):
        monitor.record_failure("binance")

    for _ in range(20):
        monitor.record_failure("binance")

    assert monitor._cooldowns["binance"] == 3600.0


def test_success_clears_the_cooldown():
    monitor, _ = _monitor()
    for _ in range(5):
        monitor.record_failure("binance")

    monitor.record_success("binance")

    assert "binance" not in monitor._cooldowns
    assert monitor.is_healthy("binance") is True


def test_can_probe_requires_an_unhealthy_source():
    monitor, _ = _monitor()

    assert monitor.can_probe("binance") is False

    for _ in range(5):
        monitor.record_failure("binance")
    assert monitor.can_probe("binance") is False


def test_can_probe_after_the_cooldown():
    monitor, clock = _monitor(cooldown=60.0)
    for _ in range(5):
        monitor.record_failure("binance")

    clock.now += 61

    assert monitor.can_probe("binance") is True


def test_begin_probe_is_allowed_once_per_cooldown():
    monitor, clock = _monitor(cooldown=60.0)
    for _ in range(5):
        monitor.record_failure("binance")
    clock.now += 61

    assert monitor.begin_probe("binance") is True
    assert monitor.begin_probe("binance") is False


def test_probe_result_records_success_or_failure():
    monitor, _ = _monitor()

    monitor.probe_result("binance", ok=True)
    assert monitor.snapshot()["binance"]["success"] == 1

    monitor.probe_result("binance", ok=False, error="down")
    assert monitor.snapshot()["binance"]["fail"] == 1
    assert monitor.snapshot()["binance"]["last_error"] == "down"


def test_healthy_sources_filters_the_ordered_list():
    monitor, _ = _monitor()
    for _ in range(5):
        monitor.record_failure("broken")

    assert monitor.healthy_sources(["broken", "fine"]) == ["fine"]


def test_healthy_sources_falls_back_to_the_full_list_when_all_are_down():
    monitor, _ = _monitor()
    for _ in range(5):
        monitor.record_failure("a")
        monitor.record_failure("b")

    assert monitor.healthy_sources(["a", "b"]) == ["a", "b"]


def test_snapshot_shape():
    monitor, _ = _monitor()
    monitor.record_success("binance", latency_ms=3.0)

    snapshot = monitor.snapshot()

    assert set(snapshot["binance"]) == {
        "ok",
        "latency_ms",
        "last_error",
        "success",
        "fail",
    }


def test_source_status_defaults():
    status = SourceStatus(name="x")

    assert status.ok is True
    assert status.success_count == 0
    assert status.fail_count == 0
