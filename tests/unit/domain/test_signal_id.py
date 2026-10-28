from datetime import UTC, datetime

from domain.signal_id import make_signal_id


def test_datetime_timestamp_uses_isoformat():
    ts = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
    result = make_signal_id("BTC/USDT", "1d", ts, "BUY")
    assert result == "BTC/USDT|1d|2026-10-28T12:00:00+00:00|BUY"


def test_string_timestamp_is_used_verbatim():
    result = make_signal_id("ETH/USDT", "4h", "2026-01-01T00:00:00Z", "SELL")
    assert result == "ETH/USDT|4h|2026-01-01T00:00:00Z|SELL"


def test_naive_datetime_has_no_offset():
    ts = datetime(2026, 5, 1, 8, 30)
    result = make_signal_id("SOL/USDT", "1h", ts, "HOLD")
    assert result == "SOL/USDT|1h|2026-05-01T08:30:00|HOLD"
