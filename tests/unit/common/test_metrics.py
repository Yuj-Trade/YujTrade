import pytest

from common import metrics


def test_prometheus_availability_is_reported_once():
    assert isinstance(metrics._PROM, bool)


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_signal_and_candidate_counters_are_updated():
    before = metrics._signals_total.labels("BTC/USDT", "1h", "buy")._value.get()

    metrics.record_signal("BTC/USDT", "1h", "buy")

    after = metrics._signals_total.labels("BTC/USDT", "1h", "buy")._value.get()
    assert after == before + 1


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_gate_rejection_counter_is_updated():
    before = metrics._gate_rejections_total.labels("min_confidence")._value.get()

    metrics.record_gate_rejection("min_confidence")

    assert metrics._gate_rejections_total.labels("min_confidence")._value.get() == before + 1


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
@pytest.mark.parametrize(("outcome", "label"), [(True, "success"), (False, "failure")])
def test_resolution_counter_maps_the_boolean(outcome, label):
    before = metrics._resolutions_total.labels(label)._value.get()

    metrics.record_resolution(outcome)

    assert metrics._resolutions_total.labels(label)._value.get() == before + 1


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_equity_and_exposure_gauges_are_set():
    metrics.set_equity(12345.0)
    metrics.set_exposure(42.5)

    assert metrics._equity._value.get() == pytest.approx(12345.0)
    assert metrics._exposure._value.get() == pytest.approx(42.5)


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_latency_observation_is_recorded():
    before = metrics._signal_latency._sum.get()

    metrics.observe_latency(0.25)

    assert metrics._signal_latency._sum.get() == pytest.approx(before + 0.25)


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_artifact_mismatch_counter_is_updated():
    before = metrics._artifact_mismatches_total._value.get()

    metrics.record_artifact_mismatch()

    assert metrics._artifact_mismatches_total._value.get() == before + 1


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_outcome_counters_are_updated():
    events_before = metrics._outcome_events_total.labels("target")._value.get()
    notifications_before = metrics._outcome_notifications_total.labels("sent")._value.get()

    metrics.record_outcome_event("target")
    metrics.record_outcome_notification("sent")

    assert metrics._outcome_events_total.labels("target")._value.get() == events_before + 1
    assert (
        metrics._outcome_notifications_total.labels("sent")._value.get() == notifications_before + 1
    )


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_order_counter_is_updated():
    before = metrics._orders_total.labels("BTC/USDT", "paper", "filled")._value.get()

    metrics.record_order("BTC/USDT", "paper", "filled")

    assert metrics._orders_total.labels("BTC/USDT", "paper", "filled")._value.get() == before + 1


@pytest.mark.skipif(not metrics._PROM, reason="prometheus_client is not installed")
def test_payload_returns_prometheus_output():
    payload, content_type = metrics.metrics_payload()

    assert isinstance(payload, bytes)
    assert payload
    assert "text/plain" in content_type


def test_metrics_server_is_not_started_when_disabled():
    assert metrics.start_metrics_server(enabled=False) is False


def test_sentry_is_not_initialised_without_a_dsn():
    assert metrics.init_sentry("") is False


@pytest.mark.skipif(metrics._PROM, reason="prometheus_client is installed")
def test_payload_reports_disabled_without_prometheus():
    payload, content_type = metrics.metrics_payload()

    assert payload == b"yujtrade_metrics_disabled"
    assert content_type == "text/plain"


@pytest.mark.skipif(metrics._PROM, reason="prometheus_client is installed")
def test_recorders_are_no_ops_without_prometheus():
    metrics.record_signal("BTC/USDT", "1h", "buy")
    metrics.record_candidate("BTC/USDT", "1h")
    metrics.record_gate_rejection("gate")
    metrics.record_resolution(True)
    metrics.record_artifact_mismatch()
    metrics.record_outcome_event("target")
    metrics.record_outcome_notification("sent")
    metrics.record_order("BTC/USDT", "paper", "filled")
    metrics.set_equity(1.0)
    metrics.set_exposure(1.0)
    metrics.observe_latency(1.0)
