from datetime import UTC, datetime, timedelta

import pytest

from application.outcome_policy import (
    NotificationPolicy,
    PolicyError,
    build_policy,
    failure_state,
    is_eligible,
)

_ALLOWED = frozenset({"1h", "4h", "1d", "1w", "1M"})


def _raw(**overrides) -> dict:
    base = {
        "outcome_notifications_mode": "off",
        "outcome_notifications_since": "",
        "outcome_notification_kinds": ["target", "stop", "expired"],
        "outcome_notification_timeframes": [],
        "outcome_watch_interval_minutes": 15,
        "outcome_notification_max_attempts": 3,
        "outcome_claim_ttl_seconds": 300,
        "outcome_watch_concurrency": 4,
    }
    base.update(overrides)
    return base


def test_the_default_configuration_is_off():
    policy = build_policy(_raw(), _ALLOWED)

    assert policy.mode == "off"
    assert policy.enabled is False
    assert policy.since is None
    assert policy.kinds == frozenset({"target", "stop", "expired"})
    assert policy.timeframes == _ALLOWED
    assert policy.max_attempts == 3
    assert policy.claim_ttl == timedelta(seconds=300)
    assert policy.watch_interval == timedelta(minutes=15)
    assert policy.concurrency == 4


def test_a_live_policy_is_enabled():
    policy = build_policy(
        _raw(
            outcome_notifications_mode="live",
            outcome_notifications_since="2026-10-01T00:00:00+00:00",
        ),
        _ALLOWED,
    )

    assert policy.enabled is True


def test_a_shadow_policy_is_enabled():
    policy = build_policy(
        _raw(
            outcome_notifications_mode="shadow",
            outcome_notifications_since="2026-10-01T00:00:00+00:00",
        ),
        _ALLOWED,
    )

    assert policy.mode == "shadow"
    assert policy.enabled is True


def test_an_unknown_mode_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_notifications_mode="loud"), _ALLOWED)


def test_a_live_mode_without_a_since_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_notifications_mode="live"), _ALLOWED)


def test_a_shadow_mode_without_a_since_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_notifications_mode="shadow"), _ALLOWED)


def test_a_since_without_a_timezone_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(
            _raw(
                outcome_notifications_mode="live", outcome_notifications_since="2026-10-01T00:00:00"
            ),
            _ALLOWED,
        )


def test_a_since_that_is_not_iso_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(
            _raw(outcome_notifications_mode="live", outcome_notifications_since="yesterday"),
            _ALLOWED,
        )


def test_the_since_is_converted_to_utc():
    policy = build_policy(
        _raw(
            outcome_notifications_mode="live",
            outcome_notifications_since="2026-10-01T04:00:00+04:00",
        ),
        _ALLOWED,
    )

    assert policy.since == datetime(2026, 10, 1, 0, tzinfo=UTC)


def test_an_empty_kind_list_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_notification_kinds=[]), _ALLOWED)


def test_an_unknown_kind_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_notification_kinds=["target", "moon"]), _ALLOWED)


def test_an_unknown_timeframe_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_notification_timeframes=["9h"]), _ALLOWED)


def test_an_empty_timeframe_list_means_every_allowed_timeframe():
    policy = build_policy(_raw(outcome_notification_timeframes=[]), _ALLOWED)

    assert policy.timeframes == _ALLOWED


def test_a_selected_timeframe_list_is_kept():
    policy = build_policy(_raw(outcome_notification_timeframes=["1d"]), _ALLOWED)

    assert policy.timeframes == frozenset({"1d"})


def test_a_non_positive_interval_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_watch_interval_minutes=0), _ALLOWED)


def test_a_non_positive_attempt_limit_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_notification_max_attempts=0), _ALLOWED)


def test_a_non_positive_claim_ttl_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_claim_ttl_seconds=0), _ALLOWED)


def test_a_non_positive_concurrency_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_watch_concurrency=0), _ALLOWED)


def test_a_non_numeric_interval_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_watch_interval_minutes="soon"), _ALLOWED)


def test_a_boolean_interval_is_rejected():
    with pytest.raises(PolicyError):
        build_policy(_raw(outcome_watch_interval_minutes=True), _ALLOWED)


def _policy(**overrides) -> NotificationPolicy:
    base = {
        "mode": "live",
        "kinds": frozenset({"target", "stop"}),
        "timeframes": frozenset({"1h", "1d"}),
        "since": None,
        "max_attempts": 3,
        "claim_ttl": timedelta(seconds=300),
        "watch_interval": timedelta(minutes=15),
        "concurrency": 4,
    }
    base.update(overrides)
    return NotificationPolicy(**base)


def test_an_unconfigured_kind_is_not_eligible():
    policy = _policy()

    assert is_eligible("expired", "1h", datetime(2026, 10, 1, tzinfo=UTC), policy) is False


def test_a_configured_kind_and_timeframe_is_eligible():
    policy = _policy()

    assert is_eligible("target", "1h", datetime(2026, 10, 1, tzinfo=UTC), policy) is True


def test_an_unconfigured_timeframe_is_not_eligible():
    policy = _policy()

    assert is_eligible("target", "4h", datetime(2026, 10, 1, tzinfo=UTC), policy) is False


def test_a_signal_older_than_the_since_bound_is_not_eligible():
    policy = _policy(since=datetime(2026, 10, 2, tzinfo=UTC))

    assert is_eligible("target", "1h", datetime(2026, 10, 1, tzinfo=UTC), policy) is False


def test_a_signal_at_the_since_bound_is_eligible():
    policy = _policy(since=datetime(2026, 10, 1, tzinfo=UTC))

    assert is_eligible("target", "1h", datetime(2026, 10, 1, tzinfo=UTC), policy) is True


def test_a_naive_creation_is_treated_as_utc():
    policy = _policy(since=datetime(2026, 10, 1, tzinfo=UTC))

    assert is_eligible("target", "1h", datetime(2026, 10, 3), policy) is True


def test_a_permanent_failure_is_abandoned():
    assert failure_state(1, True, 3) == "abandoned"


def test_a_retryable_failure_stays_pending():
    assert failure_state(1, False, 3) == "pending"


def test_a_retryable_failure_at_the_limit_is_abandoned():
    assert failure_state(3, False, 3) == "abandoned"


def test_a_retryable_failure_above_the_limit_is_abandoned():
    assert failure_state(4, False, 3) == "abandoned"
