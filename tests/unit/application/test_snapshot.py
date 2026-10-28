import dataclasses
from datetime import UTC, datetime

import pytest

from application.snapshot import MarketSnapshot, build_snapshot
from domain.types import Candle


def make_candles(count: int = 3) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            timestamp=datetime(2026, 1, 1, hour, tzinfo=UTC),
            open=100.0 + hour,
            high=105.0 + hour,
            low=99.0 + hour,
            close=104.0 + hour,
            volume=10.0,
        )
        for hour in range(count)
    )


def test_empty_candles_raise_value_error():
    with pytest.raises(ValueError, match="candles must not be empty"):
        build_snapshot(
            symbol="BTC/USDT",
            timeframe="1d",
            candles=[],
            score=80.0,
            confidence=75.0,
            side="buy",
            entry=100.0,
            stop=95.0,
            target=110.0,
        )


def test_timestamp_taken_from_last_candle():
    snapshot = build_snapshot(
        symbol="BTC/USDT",
        timeframe="1d",
        candles=make_candles(3),
        score=80.0,
        confidence=75.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=110.0,
    )
    assert snapshot.timestamp == datetime(2026, 1, 1, 2, tzinfo=UTC)


def test_candles_stored_as_tuple():
    snapshot = build_snapshot(
        symbol="BTC/USDT",
        timeframe="1d",
        candles=list(make_candles(2)),
        score=80.0,
        confidence=75.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=110.0,
    )
    assert isinstance(snapshot.candles, tuple)
    assert len(snapshot.candles) == 2


def test_defaults_applied():
    snapshot = build_snapshot(
        symbol="BTC/USDT",
        timeframe="1d",
        candles=make_candles(1),
        score=80.0,
        confidence=75.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=110.0,
    )
    assert snapshot.trend_strength == "WEAK"
    assert snapshot.volume_surge is None
    assert dict(snapshot.details) == {}


def test_explicit_optional_fields_preserved():
    snapshot = build_snapshot(
        symbol="BTC/USDT",
        timeframe="1d",
        candles=make_candles(1),
        score=80.0,
        confidence=75.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=110.0,
        trend_strength="STRONG",
        volume_surge=1.7,
        details={"adx": 30.0},
    )
    assert snapshot.trend_strength == "STRONG"
    assert snapshot.volume_surge == 1.7
    assert snapshot.details["adx"] == 30.0


def test_snapshot_is_frozen():
    snapshot = build_snapshot(
        symbol="BTC/USDT",
        timeframe="1d",
        candles=make_candles(1),
        score=80.0,
        confidence=75.0,
        side="buy",
        entry=100.0,
        stop=95.0,
        target=110.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.score = 90.0
    assert isinstance(snapshot, MarketSnapshot)
