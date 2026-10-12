"""Edge coverage for the domain outcome resolver: sell side and expiry."""

from datetime import UTC, datetime, timedelta

from domain.outcome import resolve_outcome


def _candle(ts, high, low):
    return {"timestamp": ts, "high": high, "low": low}


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
