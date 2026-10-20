"""Edge coverage for the domain outcome resolver: sell side and expiry."""

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from domain.outcome import (
    OutcomeEvent,
    Resolution,
    event_from_resolution,
    observe_signal_barrier,
    resolve_outcome,
    resolve_signal_outcome,
)

_ONE_HOUR = timedelta(hours=1)


def _candle(ts, high, low):
    return {"timestamp": ts, "high": high, "low": low}


def _full_candle(ts, high, low, close):
    return {"timestamp": ts, "high": high, "low": low, "close": close}


class TestSellSide:
    def test_sell_stop_hit(self):
        candles = [_candle(datetime(2024, 1, 1, tzinfo=UTC), 106.0, 99.0)]
        outcome = resolve_outcome(candles, "sell", 100.0, 105.0, 90.0)
        assert outcome is not None
        assert (outcome.success, outcome.exit_price, outcome.reason) == (
            False,
            105.0,
            "stop",
        )

    def test_sell_target_hit(self):
        candles = [_candle(datetime(2024, 1, 1, tzinfo=UTC), 99.0, 89.0)]
        outcome = resolve_outcome(candles, "sell", 100.0, 105.0, 90.0)
        assert outcome is not None
        assert (outcome.success, outcome.exit_price, outcome.reason) == (
            True,
            90.0,
            "target",
        )

    def test_unknown_side_returns_none(self):
        candles = [_candle(datetime(2024, 1, 1, tzinfo=UTC), 99.0, 89.0)]
        assert resolve_outcome(candles, "hold", 100.0, 105.0, 90.0) is None


class TestExpiry:
    def _window(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        return base, [
            _candle(base, 101.0, 99.0),
            _candle(base + timedelta(hours=1), 112.0, 101.0),
            _candle(base + timedelta(hours=5), 150.0, 140.0),
        ]

    def test_candles_before_creation_ignored(self):
        base, candles = self._window()
        created = base + timedelta(minutes=30)
        outcome = resolve_outcome(candles, "buy", 100.0, 95.0, 110.0, created_at=created)
        assert outcome is not None
        assert outcome.reason == "target"

    def test_candles_after_expiry_break(self):
        base, candles = self._window()
        outcome = resolve_outcome(
            candles, "buy", 100.0, 95.0, 140.0, created_at=base, expiry_hours=2
        )
        assert outcome is None


def _series(base, hours, high=101.0, low=99.0, close=100.0):
    return [_full_candle(base + timedelta(hours=index), high, low, close) for index in range(hours)]


class TestResolveSignalOutcome:
    def test_a_target_hit_reports_the_target_and_the_candle_time(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3)
        candles[1] = _full_candle(base + timedelta(hours=1), 112.0, 101.0, 110.0)

        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "target"
        assert resolution.exit_price == 110.0
        assert resolution.exit_at == base + timedelta(hours=1)
        assert resolution.candles_used == 2

    def test_a_stop_hit_reports_the_stop_and_the_candle_time(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3)
        candles[0] = _full_candle(base, 101.0, 94.0, 100.0)

        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "stop"
        assert resolution.exit_price == 95.0
        assert resolution.exit_at == base
        assert resolution.candles_used == 1

    def test_the_stop_wins_when_one_candle_touches_both_levels(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3)
        candles[0] = _full_candle(base, 112.0, 94.0, 100.0)

        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "stop"

    def test_an_expired_signal_uses_the_close_of_the_last_candle(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3, close=100.0)
        candles[2] = _full_candle(base + timedelta(hours=2), 101.0, 99.0, 103.25)

        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "expired"
        assert resolution.exit_price == 103.25
        assert resolution.exit_at == base + timedelta(hours=2)
        assert resolution.candles_used == 3

    def test_an_incomplete_window_is_no_data(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 2)

        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 12.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "no_data"
        assert resolution.exit_price is None
        assert resolution.exit_at is None
        assert resolution.candles_used == 0

    def test_a_window_that_starts_too_late_is_no_data(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3)
        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base + timedelta(hours=5), 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "no_data"

    def test_an_empty_candle_set_is_no_data(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)

        resolution = resolve_signal_outcome([], "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR)

        assert resolution.exit_reason == "no_data"

    def test_a_sell_target_hit_is_reported(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3)
        candles[1] = _full_candle(base + timedelta(hours=1), 99.0, 89.0, 90.0)

        resolution = resolve_signal_outcome(
            candles, "sell", 100.0, 105.0, 90.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "target"
        assert resolution.exit_price == 90.0

    def test_a_sell_stop_hit_is_reported(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3)
        candles[0] = _full_candle(base, 106.0, 99.0, 100.0)

        resolution = resolve_signal_outcome(
            candles, "sell", 100.0, 105.0, 90.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "stop"
        assert resolution.exit_price == 105.0

    def test_an_unsupported_side_raises(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)

        with pytest.raises(ValueError):
            resolve_signal_outcome(
                _series(base, 3), "hold", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
            )

    def test_a_naive_creation_raises(self):
        base = datetime(2024, 1, 1)

        with pytest.raises(ValueError):
            resolve_signal_outcome(
                _series(base.replace(tzinfo=UTC), 3),
                "buy",
                100.0,
                95.0,
                110.0,
                base,
                3.0,
                _ONE_HOUR,
            )

    def test_a_non_positive_expiry_raises(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)

        with pytest.raises(ValueError):
            resolve_signal_outcome(
                _series(base, 3), "buy", 100.0, 95.0, 110.0, base, 0.0, _ONE_HOUR
            )

    def test_a_non_positive_candle_duration_raises(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)

        with pytest.raises(ValueError):
            resolve_signal_outcome(
                _series(base, 3), "buy", 100.0, 95.0, 110.0, base, 3.0, timedelta(0)
            )

    def test_candles_without_a_timestamp_are_ignored(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [{"high": 112.0, "low": 101.0, "close": 110.0}]
        candles.extend(_series(base, 3))

        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "expired"

    def test_a_candle_without_a_close_cannot_expire(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [_candle(base + timedelta(hours=index), 101.0, 99.0) for index in range(3)]

        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
        )

        assert resolution.exit_reason == "no_data"

    def test_the_outcome_of_a_hit_matches_the_previous_resolver(self):
        base = datetime(2024, 1, 1, tzinfo=UTC)
        candles = _series(base, 3)
        candles[1] = _full_candle(base + timedelta(hours=1), 112.0, 101.0, 110.0)

        previous = resolve_outcome(
            candles, "buy", 100.0, 95.0, 110.0, created_at=base, expiry_hours=3.0
        )
        resolution = resolve_signal_outcome(
            candles, "buy", 100.0, 95.0, 110.0, base, 3.0, _ONE_HOUR
        )

        assert previous is not None
        assert resolution.exit_price == previous.exit_price
        assert (resolution.exit_reason == "target") == previous.success


class TestObserveSignalBarrier:
    def test_a_target_touch_is_detected_for_a_buy(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [
            _full_candle(base, 101.0, 99.0, 100.0),
            _full_candle(base + _ONE_HOUR, 112.0, 101.0, 110.0),
        ]

        observed = observe_signal_barrier(
            candles, "buy", 95.0, 110.0, base, base + timedelta(hours=2), _ONE_HOUR
        )

        assert observed is not None
        assert observed.exit_reason == "target"
        assert observed.exit_price == 110.0
        assert observed.exit_at == base + _ONE_HOUR
        assert observed.candles_used == 2

    def test_a_stop_touch_is_detected_for_a_sell(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [
            _full_candle(base, 101.0, 99.0, 100.0),
            _full_candle(base + _ONE_HOUR, 106.0, 101.0, 105.0),
        ]

        observed = observe_signal_barrier(
            candles, "sell", 105.0, 90.0, base, base + timedelta(hours=2), _ONE_HOUR
        )

        assert observed is not None
        assert observed.exit_reason == "stop"
        assert observed.exit_price == 105.0
        assert observed.exit_at == base + _ONE_HOUR

    def test_the_stop_wins_when_one_candle_touches_both_levels(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [_full_candle(base, 112.0, 94.0, 100.0)]

        observed = observe_signal_barrier(
            candles, "buy", 95.0, 110.0, base, base + timedelta(hours=1), _ONE_HOUR
        )

        assert observed is not None
        assert observed.exit_reason == "stop"

    def test_a_candle_that_is_not_closed_is_not_used(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [
            _full_candle(base, 101.0, 99.0, 100.0),
            _full_candle(base + _ONE_HOUR, 112.0, 101.0, 110.0),
        ]

        observed = observe_signal_barrier(
            candles, "buy", 95.0, 110.0, base, base + timedelta(hours=1), _ONE_HOUR
        )

        assert observed is None

    def test_a_window_that_starts_too_late_is_not_observed(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)
        candles = [_full_candle(base + timedelta(hours=2), 112.0, 101.0, 110.0)]

        observed = observe_signal_barrier(
            candles, "buy", 95.0, 110.0, base, base + timedelta(hours=3), _ONE_HOUR
        )

        assert observed is None

    def test_an_empty_candle_set_is_not_observed(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)

        observed = observe_signal_barrier(
            [], "buy", 95.0, 110.0, base, base + timedelta(hours=3), _ONE_HOUR
        )

        assert observed is None

    def test_an_unsupported_side_raises(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)

        with pytest.raises(ValueError):
            observe_signal_barrier([], "hold", 95.0, 110.0, base, base, _ONE_HOUR)

    def test_a_naive_timestamp_raises(self):
        base = datetime(2026, 1, 1)

        with pytest.raises(ValueError):
            observe_signal_barrier([], "buy", 95.0, 110.0, base, base, _ONE_HOUR)

    def test_a_non_positive_candle_duration_raises(self):
        base = datetime(2026, 1, 1, tzinfo=UTC)

        with pytest.raises(ValueError):
            observe_signal_barrier([], "buy", 95.0, 110.0, base, base, timedelta(0))


class TestOutcomeEvent:
    def test_a_valid_event_is_accepted(self):
        event = OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 1, 1, tzinfo=UTC))

        assert event.kind == "target"
        assert event.price == 110.0

    def test_an_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            OutcomeEvent("sig-1", "timeout", 110.0, datetime(2026, 1, 1, tzinfo=UTC))

    def test_a_zero_price_raises(self):
        with pytest.raises(ValueError):
            OutcomeEvent("sig-1", "target", 0.0, datetime(2026, 1, 1, tzinfo=UTC))

    def test_a_negative_price_raises(self):
        with pytest.raises(ValueError):
            OutcomeEvent("sig-1", "target", -1.0, datetime(2026, 1, 1, tzinfo=UTC))

    def test_a_non_finite_price_raises(self):
        with pytest.raises(ValueError):
            OutcomeEvent("sig-1", "target", math.inf, datetime(2026, 1, 1, tzinfo=UTC))

    def test_a_naive_timestamp_raises(self):
        with pytest.raises(ValueError):
            OutcomeEvent("sig-1", "target", 110.0, datetime(2026, 1, 1))

    def test_an_empty_signal_id_raises(self):
        with pytest.raises(ValueError):
            OutcomeEvent("", "target", 110.0, datetime(2026, 1, 1, tzinfo=UTC))

    def test_a_resolution_becomes_an_event(self):
        resolution = Resolution("target", 110.0, datetime(2026, 1, 1, tzinfo=UTC), 2)

        event = event_from_resolution("sig-1", resolution)

        assert event is not None
        assert event.signal_id == "sig-1"
        assert event.kind == "target"
        assert event.price == 110.0

    def test_a_no_data_resolution_becomes_no_event(self):
        resolution = Resolution("no_data", None, None, 0)

        assert event_from_resolution("sig-1", resolution) is None


class TestObserveSignalBarrierParity:
    def test_the_observation_matches_the_final_resolution(self):
        rng = random.Random(20261020)
        created = datetime(2026, 1, 1, tzinfo=UTC)
        expiry = 24
        duration = _ONE_HOUR
        compared = 0

        for _ in range(300):
            side = rng.choice(["buy", "sell"])
            stop = 95.0 if side == "buy" else 105.0
            target = 110.0 if side == "buy" else 90.0
            candles = []
            for index in range(-1, expiry + 1):
                candles.append(
                    {
                        "timestamp": created + timedelta(hours=index),
                        "high": 100.0 + rng.uniform(0.0, 14.0),
                        "low": 100.0 - rng.uniform(0.0, 14.0),
                        "close": 100.0 + rng.uniform(-3.0, 3.0),
                    }
                )
            hours = rng.randint(1, expiry)
            observed_until = created + timedelta(hours=hours)

            observed = observe_signal_barrier(
                candles, side, stop, target, created, observed_until, duration
            )
            if observed is None:
                continue
            compared += 1
            final = resolve_signal_outcome(
                candles,
                side,
                100.0,
                stop,
                target,
                created_at=created,
                expiry_hours=expiry,
                candle_duration=duration,
            )

            assert final.exit_reason == observed.exit_reason
            assert final.exit_price == observed.exit_price
            assert final.exit_at == observed.exit_at
            assert final.candles_used == observed.candles_used

        assert compared > 0
