from datetime import UTC, datetime

import pytest

from domain.performance import (
    ResolutionRecord,
    format_utc_timestamp,
    parse_utc_timestamp,
)


def _record(
    side: str = "buy",
    entry: float = 100.0,
    stop: float = 90.0,
    exit_price: float | None = 120.0,
    exit_reason: str = "target",
    exit_at: datetime | None = datetime(2026, 10, 1, 14, tzinfo=UTC),
) -> ResolutionRecord:
    return ResolutionRecord(
        signal_id="sig-1",
        symbol="BTC/USDT",
        timeframe="1h",
        side=side,
        entry=entry,
        stop=stop,
        target=120.0,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        exit_at=exit_at,
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="paper-resolution-v1",
    )


def test_a_valid_record_is_accepted():
    record = _record()

    assert record.utc_created_at() == datetime(2026, 10, 1, 10, tzinfo=UTC)
    assert record.utc_exit_at() == datetime(2026, 10, 1, 14, tzinfo=UTC)


def test_a_no_data_record_has_no_exit_time():
    record = _record(exit_price=None, exit_reason="no_data", exit_at=None)

    assert record.utc_exit_at() is None


def test_resolution_record_rejects_naive_timestamps():
    with pytest.raises(ValueError):
        ResolutionRecord(
            signal_id="sig-1",
            symbol="BTC/USDT",
            timeframe="1h",
            side="buy",
            entry=100.0,
            stop=90.0,
            target=120.0,
            created_at=datetime(2026, 10, 1, 10),
            exit_at=datetime(2026, 10, 1, 14),
            exit_price=120.0,
            exit_reason="target",
            candles_used=4,
            resolver_version="v1",
        )


def test_resolution_record_rejects_stop_on_wrong_side():
    with pytest.raises(ValueError):
        _record(side="buy", entry=100.0, stop=105.0)
    with pytest.raises(ValueError):
        _record(side="sell", entry=100.0, stop=95.0)


def test_resolution_record_rejects_price_for_no_data():
    with pytest.raises(ValueError):
        _record(exit_price=100.0, exit_reason="no_data", exit_at=None)


def test_resolution_record_rejects_exit_time_for_no_data():
    with pytest.raises(ValueError):
        _record(exit_price=None, exit_reason="no_data")


def test_resolution_record_requires_price_for_resolved_exit():
    with pytest.raises(ValueError):
        _record(exit_price=None, exit_reason="expired")


def test_resolution_record_requires_exit_time_for_resolved_exit():
    with pytest.raises(ValueError):
        _record(exit_at=None)


def test_resolution_record_rejects_an_exit_before_the_creation():
    with pytest.raises(ValueError):
        _record(exit_at=datetime(2026, 10, 1, 9, tzinfo=UTC))


def test_resolution_record_rejects_unknown_exit_reason():
    with pytest.raises(ValueError):
        _record(exit_reason="timeout")


def test_resolution_record_rejects_unknown_side():
    with pytest.raises(ValueError):
        _record(side="long")


def test_resolution_record_rejects_a_non_positive_entry():
    with pytest.raises(ValueError):
        _record(entry=0.0)


def test_resolution_record_rejects_a_negative_candle_count():
    with pytest.raises(ValueError):
        ResolutionRecord(
            signal_id="sig-1",
            symbol="BTC/USDT",
            timeframe="1h",
            side="buy",
            entry=100.0,
            stop=90.0,
            target=120.0,
            created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
            exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
            exit_price=120.0,
            exit_reason="target",
            candles_used=-1,
            resolver_version="v1",
        )


def test_resolution_record_rejects_an_empty_signal_id():
    with pytest.raises(ValueError):
        ResolutionRecord(
            signal_id="",
            symbol="BTC/USDT",
            timeframe="1h",
            side="buy",
            entry=100.0,
            stop=90.0,
            target=120.0,
            created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
            exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
            exit_price=120.0,
            exit_reason="target",
            candles_used=4,
            resolver_version="v1",
        )


def test_timestamps_use_the_fixed_utc_format():
    formatted = format_utc_timestamp(datetime(2026, 10, 1, 14, tzinfo=UTC))

    assert formatted == "2026-10-01T14:00:00.000000+00:00"


def test_timestamps_round_trip_through_the_fixed_format():
    original = datetime(2026, 10, 1, 14, 30, 15, 123456, tzinfo=UTC)

    assert parse_utc_timestamp(format_utc_timestamp(original)) == original


def test_lexicographic_timestamp_order_matches_chronological_order():
    earlier = format_utc_timestamp(datetime(2026, 10, 1, 14, tzinfo=UTC))
    later = format_utc_timestamp(datetime(2026, 10, 1, 15, tzinfo=UTC))

    assert earlier < later
