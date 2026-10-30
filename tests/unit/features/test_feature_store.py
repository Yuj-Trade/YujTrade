"""Feature store: schema, triggers, labelling, leakage and the training source."""

import asyncio
from datetime import UTC, datetime, timedelta

import aiosqlite
import pandas as pd
import pytest

from features.feature_store import (
    FeatureStore,
    canonical_feature_set_hash,
    is_label_closed,
    label_candle_time,
    vector_from_row,
)

_BASE = datetime(2026, 10, 1, tzinfo=UTC)
_FEATURES = ["close", "volume", "rsi"]


def _values(close=100.0, volume=10.0, rsi=50.0):
    return {"close": close, "volume": volume, "rsi": rsi}


def _store(tmp_path) -> FeatureStore:
    return FeatureStore(tmp_path / "feature_store.db")


def _candles(start: datetime, count: int) -> pd.DataFrame:
    index = [start + timedelta(hours=index) for index in range(count)]
    return pd.DataFrame(
        {"close": [100.0 + index for index in range(count)]},
        index=pd.DatetimeIndex(index),
    )


def test_the_schema_creates_both_tables_and_their_triggers(tmp_path):
    store = _store(tmp_path)
    asyncio.run(store.initialize())

    async def _query():
        async with aiosqlite.connect(store.path) as connection:
            cursor = await connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
            )
            return [row[0] for row in await cursor.fetchall()]

    names = asyncio.run(_query())
    assert "feature_vectors_no_update" in names
    assert "feature_vectors_no_delete" in names
    assert "feature_labels_no_update" in names
    assert "feature_labels_no_delete" in names


def test_a_vector_is_recorded_once(tmp_path):
    store = _store(tmp_path)

    first = asyncio.run(store.record_vector("BTC/USDT", "1h", _BASE, _FEATURES, _values()))
    second = asyncio.run(store.record_vector("BTC/USDT", "1h", _BASE, _FEATURES, _values()))

    assert first is True
    assert second is False


def test_the_tables_reject_update_and_delete(tmp_path):
    store = _store(tmp_path)
    asyncio.run(store.record_vector("BTC/USDT", "1h", _BASE, _FEATURES, _values()))

    async def _attempt(sql):
        async with aiosqlite.connect(store.path) as connection:
            with pytest.raises(aiosqlite.IntegrityError):
                await connection.execute(sql)

    asyncio.run(_attempt("UPDATE feature_vectors SET values_json = '{}'"))
    asyncio.run(_attempt("DELETE FROM feature_vectors"))


def test_a_non_finite_value_is_rejected_and_not_stored(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError):
        asyncio.run(
            store.record_vector("BTC/USDT", "1h", _BASE, _FEATURES, _values(close=float("nan")))
        )
    with pytest.raises(ValueError):
        asyncio.run(
            store.record_vector("BTC/USDT", "1h", _BASE, _FEATURES, _values(rsi=float("inf")))
        )


def test_a_missing_feature_is_rejected(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(store.record_vector("BTC/USDT", "1h", _BASE, _FEATURES, {"close": 1.0}))


def test_the_feature_set_hash_is_stable_and_order_sensitive():
    assert canonical_feature_set_hash(_FEATURES) == canonical_feature_set_hash(list(_FEATURES))
    assert canonical_feature_set_hash(_FEATURES) != canonical_feature_set_hash(
        list(reversed(_FEATURES))
    )


def test_a_label_is_written_only_for_a_closed_candle(tmp_path):
    store = _store(tmp_path)
    future = datetime.now(UTC) + timedelta(hours=1)
    asyncio.run(store.record_vector("BTC/USDT", "1h", future, _FEATURES, _values()))

    written = asyncio.run(store.label_pending("BTC/USDT", "1h", _candles(future, 3)))

    assert written == 0


def test_a_label_is_written_for_a_closed_candle(tmp_path):
    store = _store(tmp_path)
    old = datetime.now(UTC) - timedelta(days=2)
    old = old.replace(minute=0, second=0, microsecond=0)
    asyncio.run(store.record_vector("BTC/USDT", "1h", old, _FEATURES, _values()))
    candles = _candles(old, 3)

    written = asyncio.run(store.label_pending("BTC/USDT", "1h", candles))

    assert written == 1


def test_the_label_is_the_close_of_the_next_candle(tmp_path):
    store = _store(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    asyncio.run(store.record_vector("BTC/USDT", "1h", old, _FEATURES, _values()))
    candles = _candles(old, 3)
    asyncio.run(store.label_pending("BTC/USDT", "1h", candles))

    frame = asyncio.run(
        store.training_frame("BTC/USDT", "1h", _FEATURES, label_before=datetime.now(UTC))
    )

    assert len(frame) == 1
    assert frame["label_close"].iloc[0] == pytest.approx(101.0)


def test_the_training_frame_never_sees_a_label_after_the_cutoff(tmp_path):
    store = _store(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    asyncio.run(store.record_vector("BTC/USDT", "1h", old, _FEATURES, _values()))
    asyncio.run(store.label_pending("BTC/USDT", "1h", _candles(old, 3)))

    frame = asyncio.run(store.training_frame("BTC/USDT", "1h", _FEATURES, label_before=old))

    assert frame.empty


def test_the_training_frame_excludes_a_different_feature_set(tmp_path):
    store = _store(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    asyncio.run(store.record_vector("BTC/USDT", "1h", old, ["close"], {"close": 100.0}))
    asyncio.run(store.label_pending("BTC/USDT", "1h", _candles(old, 3)))

    frame = asyncio.run(
        store.training_frame("BTC/USDT", "1h", _FEATURES, label_before=datetime.now(UTC))
    )

    assert frame.empty


def test_the_training_frame_has_the_feature_columns_in_order(tmp_path):
    store = _store(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    asyncio.run(store.record_vector("BTC/USDT", "1h", old, _FEATURES, _values()))
    asyncio.run(store.label_pending("BTC/USDT", "1h", _candles(old, 3)))

    frame = asyncio.run(
        store.training_frame("BTC/USDT", "1h", _FEATURES, label_before=datetime.now(UTC))
    )

    assert list(frame.columns) == _FEATURES + ["label_close"]


def test_count_labeled_matches_the_stored_rows(tmp_path):
    store = _store(tmp_path)
    old = (datetime.now(UTC) - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    asyncio.run(store.record_vector("BTC/USDT", "1h", old, _FEATURES, _values()))
    asyncio.run(store.label_pending("BTC/USDT", "1h", _candles(old, 3)))

    assert asyncio.run(store.count_labeled("BTC/USDT", "1h", _FEATURES)) == 1
    assert asyncio.run(store.count_labeled("BTC/USDT", "1h", ["close"])) == 0


def test_the_label_time_and_closed_helpers():
    assert label_candle_time(_BASE, "1h") == _BASE + timedelta(hours=1)
    assert is_label_closed(_BASE, "1h", _BASE + timedelta(hours=2)) is True
    assert is_label_closed(_BASE, "1h", _BASE + timedelta(minutes=90)) is False


def test_vector_from_row_reads_the_named_features():
    series = pd.Series({"close": 1.0, "volume": 2.0, "rsi": 3.0})
    assert vector_from_row(series, _FEATURES) == {"close": 1.0, "volume": 2.0, "rsi": 3.0}
    with pytest.raises(ValueError):
        vector_from_row(series, ["close", "missing"])


def test_a_naive_candle_time_is_rejected(tmp_path):
    store = _store(tmp_path)
    naive = datetime(2026, 10, 1)
    with pytest.raises(ValueError):
        asyncio.run(store.record_vector("BTC/USDT", "1h", naive, _FEATURES, _values()))


def test_an_empty_feature_list_is_rejected(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(store.record_vector("BTC/USDT", "1h", _BASE, [], {}))
