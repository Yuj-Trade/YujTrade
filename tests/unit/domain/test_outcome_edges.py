"""Edge coverage for the domain outcome resolver: sell side and expiry."""

from datetime import UTC, datetime, timedelta

import pytest

from domain.outcome import resolve_outcome, resolve_signal_outcome

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
