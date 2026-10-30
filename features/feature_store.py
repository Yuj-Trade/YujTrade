import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pandas as pd

from common.constants import candle_duration

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_vectors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  candle_time_utc TEXT NOT NULL,
  feature_set_hash TEXT NOT NULL,
  feature_list_json TEXT NOT NULL,
  values_json TEXT NOT NULL,
  recorded_at_utc TEXT NOT NULL,
  UNIQUE (symbol, timeframe, candle_time_utc, feature_set_hash)
);
CREATE TABLE IF NOT EXISTS feature_labels (
  feature_vector_id INTEGER PRIMARY KEY REFERENCES feature_vectors(id),
  label_candle_time_utc TEXT NOT NULL,
  label_close REAL NOT NULL,
  recorded_at_utc TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS feature_vectors_no_update
BEFORE UPDATE ON feature_vectors
BEGIN
    SELECT RAISE(ABORT, 'feature_vectors is append-only');
END;
CREATE TRIGGER IF NOT EXISTS feature_vectors_no_delete
BEFORE DELETE ON feature_vectors
BEGIN
    SELECT RAISE(ABORT, 'feature_vectors is append-only');
END;
CREATE TRIGGER IF NOT EXISTS feature_labels_no_update
BEFORE UPDATE ON feature_labels
BEGIN
    SELECT RAISE(ABORT, 'feature_labels is append-only');
END;
CREATE TRIGGER IF NOT EXISTS feature_labels_no_delete
BEFORE DELETE ON feature_labels
BEGIN
    SELECT RAISE(ABORT, 'feature_labels is append-only');
END;
"""

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f+00:00"


def canonical_feature_set_hash(feature_list: Sequence[str]) -> str:
    text = json.dumps(list(feature_list), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_values(values: Mapping[str, float], feature_list: Sequence[str]) -> str:
    payload: dict[str, float] = {}
    for name in feature_list:
        if name not in values:
            raise ValueError(f"feature {name!r} is missing from the vector")
        value = float(values[name])
        if not math.isfinite(value):
            raise ValueError(f"feature {name!r} is not finite")
        payload[name] = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _format(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class FeatureStore:
    def __init__(self, path: str | Path = "runs/feature_store.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        connection = await aiosqlite.connect(self.path)
        try:
            await connection.executescript(_SCHEMA)
            await connection.commit()
        finally:
            await connection.close()

    async def record_vector(
        self,
        symbol: str,
        timeframe: str,
        candle_time: datetime,
        feature_list: Sequence[str],
        values: Mapping[str, float],
    ) -> bool:
        if candle_time.tzinfo is None:
            raise ValueError("candle_time must be timezone-aware")
        if not feature_list:
            raise ValueError("feature_list must not be empty")
        canonical = _canonical_values(values, feature_list)
        feature_hash = canonical_feature_set_hash(feature_list)
        connection = await aiosqlite.connect(self.path)
        try:
            await connection.executescript(_SCHEMA)
            await connection.execute(
                "INSERT INTO feature_vectors(symbol, timeframe, candle_time_utc, "
                "feature_set_hash, feature_list_json, values_json, recorded_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    timeframe,
                    _format(candle_time),
                    feature_hash,
                    json.dumps(list(feature_list), separators=(",", ":")),
                    canonical,
                    _format(datetime.now(UTC)),
                ),
            )
            await connection.commit()
            return True
        except aiosqlite.IntegrityError:
            return False
        finally:
            await connection.close()

    async def label_pending(
        self,
        symbol: str,
        timeframe: str,
        candles: pd.DataFrame,
    ) -> int:
        if candles is None or candles.empty:
            return 0
        duration = candle_duration(timeframe)
        closes = {
            _parse(index.isoformat()) if hasattr(index, "isoformat") else index: float(row["close"])
            for index, row in candles.iterrows()
        }
        connection = await aiosqlite.connect(self.path)
        try:
            await connection.executescript(_SCHEMA)
            cursor = await connection.execute(
                "SELECT vectors.id, vectors.candle_time_utc FROM feature_vectors AS vectors "
                "LEFT JOIN feature_labels AS labels ON labels.feature_vector_id = vectors.id "
                "WHERE vectors.symbol = ? AND vectors.timeframe = ? "
                "AND labels.feature_vector_id IS NULL",
                (symbol, timeframe),
            )
            rows = await cursor.fetchall()
            written = 0
            for vector_id, candle_time in rows:
                label_time = _parse(str(candle_time)) + duration
                close = closes.get(label_time)
                if close is None:
                    continue
                if label_time + duration > datetime.now(UTC):
                    continue
                await connection.execute(
                    "INSERT INTO feature_labels(feature_vector_id, label_candle_time_utc, "
                    "label_close, recorded_at_utc) VALUES (?, ?, ?, ?)",
                    (int(vector_id), _format(label_time), float(close), _format(datetime.now(UTC))),
                )
                written += 1
            await connection.commit()
            return written
        finally:
            await connection.close()

    async def training_frame(
        self,
        symbol: str,
        timeframe: str,
        feature_list: Sequence[str],
        *,
        label_before: datetime,
    ) -> pd.DataFrame:
        if label_before.tzinfo is None:
            raise ValueError("label_before must be timezone-aware")
        feature_hash = canonical_feature_set_hash(feature_list)
        connection = await aiosqlite.connect(self.path)
        try:
            await connection.executescript(_SCHEMA)
            cursor = await connection.execute(
                "SELECT vectors.candle_time_utc, vectors.values_json, labels.label_close "
                "FROM feature_vectors AS vectors "
                "JOIN feature_labels AS labels ON labels.feature_vector_id = vectors.id "
                "WHERE vectors.symbol = ? AND vectors.timeframe = ? "
                "AND vectors.feature_set_hash = ? AND labels.label_candle_time_utc <= ? "
                "ORDER BY vectors.candle_time_utc",
                (symbol, timeframe, feature_hash, _format(label_before)),
            )
            rows = await cursor.fetchall()
        finally:
            await connection.close()
        if not rows:
            return pd.DataFrame(columns=list(feature_list) + ["label_close"])
        records: list[dict[str, Any]] = []
        index: list[datetime] = []
        for candle_time, values_json, label_close in rows:
            values = json.loads(str(values_json))
            record = {name: float(values[name]) for name in feature_list}
            record["label_close"] = float(label_close)
            records.append(record)
            index.append(_parse(str(candle_time)))
        return pd.DataFrame(records, index=pd.DatetimeIndex(index))

    async def count_labeled(self, symbol: str, timeframe: str, feature_list: Sequence[str]) -> int:
        feature_hash = canonical_feature_set_hash(feature_list)
        connection = await aiosqlite.connect(self.path)
        try:
            await connection.executescript(_SCHEMA)
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM feature_vectors AS vectors "
                "JOIN feature_labels AS labels ON labels.feature_vector_id = vectors.id "
                "WHERE vectors.symbol = ? AND vectors.timeframe = ? "
                "AND vectors.feature_set_hash = ?",
                (symbol, timeframe, feature_hash),
            )
            row = await cursor.fetchone()
        finally:
            await connection.close()
        return int(row[0]) if row else 0

    async def close(self) -> None:
        return None


def vector_from_row(series: pd.Series, feature_list: Sequence[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for name in feature_list:
        if name not in series.index:
            raise ValueError(f"feature {name!r} is missing")
        values[name] = float(series[name])
    return values


def label_candle_time(candle_time: datetime, timeframe: str) -> datetime:
    return candle_time + candle_duration(timeframe)


def is_label_closed(candle_time: datetime, timeframe: str, now: datetime) -> bool:
    duration = candle_duration(timeframe)
    return candle_time + duration + duration <= now
