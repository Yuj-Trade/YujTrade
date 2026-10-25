import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
import pandas as pd

from config.logger import logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    ts INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, ts)
)
"""

_INDEX = "CREATE INDEX IF NOT EXISTS idx_candles_series ON candles(symbol, timeframe, ts DESC)"

_COLUMNS = ["open", "high", "low", "close", "volume"]


class OhlcvStore:
    def __init__(
        self,
        path: str | Path = "runs/ohlcv.db",
        max_rows_per_series: int = 5000,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_rows_per_series = int(max_rows_per_series)
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._initialized = False
        self._reported: set[str] = set()

    def _report_once(self, operation: str, exc: Exception) -> None:
        if operation in self._reported:
            return
        self._reported.add(operation)
        logger.warning(f"OHLCV store {operation} failed: {exc}. Continuing without it.")

    async def _connect(self) -> aiosqlite.Connection:
        if self._connection is not None:
            return self._connection
        connection = await aiosqlite.connect(self.path, timeout=30.0)
        if not self._initialized:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA busy_timeout=30000")
            await connection.execute(_SCHEMA)
            await connection.execute(_INDEX)
            await connection.commit()
            self._initialized = True
        self._connection = connection
        return connection

    @staticmethod
    def _rows(symbol: str, timeframe: str, frame: pd.DataFrame) -> list[tuple]:
        if frame is None or frame.empty:
            return []
        data = frame.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            if "timestamp" not in data.columns:
                return []
            data["timestamp"] = pd.to_datetime(data["timestamp"], unit="ms", utc=True)
            data = data.set_index("timestamp")
        if data.index.tz is None:
            data.index = data.index.tz_localize("UTC")

        for column in _COLUMNS:
            if column not in data.columns:
                data[column] = 0.0

        timestamps = data.index.as_unit("s").asi8.tolist()
        values = data[_COLUMNS].to_numpy(dtype=float)
        return [
            (
                symbol.upper(),
                timeframe,
                int(ts),
                float(row[0]),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
            )
            for ts, row in zip(timestamps, values, strict=True)
        ]

    async def write_many(self, symbol: str, timeframe: str, frame: pd.DataFrame) -> int:
        rows = self._rows(symbol, timeframe, frame)
        if not rows:
            return 0
        async with self._lock:
            try:
                connection = await self._connect()
                await connection.executemany(
                    "INSERT INTO candles(symbol, timeframe, ts, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(symbol, timeframe, ts) DO UPDATE SET "
                    "open=excluded.open, high=excluded.high, low=excluded.low, "
                    "close=excluded.close, volume=excluded.volume",
                    rows,
                )
                await connection.commit()
                await self._prune(connection, symbol.upper(), timeframe)
                return len(rows)
            except Exception as exc:
                self._report_once("write", exc)
                return 0

    async def _prune(self, connection: aiosqlite.Connection, symbol: str, timeframe: str) -> None:
        if self.max_rows_per_series <= 0:
            return
        await connection.execute(
            "DELETE FROM candles WHERE symbol = ? AND timeframe = ? AND ts < ("
            "SELECT ts FROM candles WHERE symbol = ? AND timeframe = ? "
            "ORDER BY ts DESC LIMIT 1 OFFSET ?)",
            (
                symbol,
                timeframe,
                symbol,
                timeframe,
                self.max_rows_per_series - 1,
            ),
        )
        await connection.commit()

    async def read(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
        if limit <= 0:
            return None
        async with self._lock:
            try:
                connection = await self._connect()
                cursor = await connection.execute(
                    "SELECT ts, open, high, low, close, volume FROM candles "
                    "WHERE symbol = ? AND timeframe = ? ORDER BY ts DESC LIMIT ?",
                    (symbol.upper(), timeframe, int(limit)),
                )
                rows = await cursor.fetchall()
            except Exception as exc:
                self._report_once("read", exc)
                return None

        if not rows:
            return None

        frame = pd.DataFrame(rows, columns=["timestamp", *_COLUMNS]).sort_values(
            "timestamp", ignore_index=True
        )
        frame.index = pd.to_datetime(frame.pop("timestamp"), unit="s", utc=True)
        frame.index.name = "timestamp"
        return frame

    async def coverage(self, symbol: str, timeframe: str) -> dict[str, Any]:
        async with self._lock:
            try:
                connection = await self._connect()
                cursor = await connection.execute(
                    "SELECT COUNT(*), MIN(ts), MAX(ts) FROM candles "
                    "WHERE symbol = ? AND timeframe = ?",
                    (symbol.upper(), timeframe),
                )
                row = await cursor.fetchone()
            except Exception as exc:
                self._report_once("coverage", exc)
                return {"rows": 0, "first_ts": None, "last_ts": None}

        return {
            "rows": int(row[0]) if row else 0,
            "first_ts": int(row[1]) if row and row[1] is not None else None,
            "last_ts": int(row[2]) if row and row[2] is not None else None,
        }

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                try:
                    await self._connection.close()
                except Exception as exc:
                    self._report_once("close", exc)
                self._connection = None
