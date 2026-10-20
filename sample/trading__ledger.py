import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from config.logger import logger
from domain.performance import ResolutionRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    filled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equity REAL NOT NULL,
    mark_prices TEXT NOT NULL,
    captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    created_at_utc TEXT NOT NULL,
    resolved_at_utc TEXT NOT NULL,
    exit_price REAL,
    exit_reason TEXT NOT NULL CHECK (exit_reason IN ('stop', 'target', 'expired', 'no_data')),
    candles_used INTEGER NOT NULL CHECK (candles_used >= 0),
    resolver_version TEXT NOT NULL,
    CHECK ((exit_reason = 'no_data') = (exit_price IS NULL))
);
CREATE TRIGGER IF NOT EXISTS signal_resolutions_no_update
BEFORE UPDATE ON signal_resolutions
BEGIN
    SELECT RAISE(ABORT, 'signal_resolutions is append-only');
END;
CREATE TRIGGER IF NOT EXISTS signal_resolutions_no_delete
BEFORE DELETE ON signal_resolutions
BEGIN
    SELECT RAISE(ABORT, 'signal_resolutions is append-only');
END;
"""

_POSITIONS_UPDATED_AT = "ALTER TABLE positions ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"


class PaperLedger:
    def __init__(self, path: str | Path = "runs/paper_ledger.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def _connect(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self.path)
        await connection.executescript(_SCHEMA)
        try:
            await connection.execute(_POSITIONS_UPDATED_AT)
        except aiosqlite.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        await connection.commit()
        return connection

    async def initialize(self) -> None:
        connection = await self._connect()
        await connection.close()

    async def append_order(
        self, signal_id: str, symbol: str, side: str, quantity: float
    ) -> int | None:
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                "INSERT INTO orders(signal_id, symbol, side, quantity, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (signal_id, symbol, side, float(quantity), datetime.now(UTC).isoformat()),
            )
            await connection.commit()
            return int(cursor.lastrowid)
        except aiosqlite.IntegrityError:
            return None
        finally:
            await connection.close()

    async def snapshot_equity(
        self, cash: float, positions: Iterable[dict[str, Any]], marks: dict[str, float]
    ) -> float:
        equity = float(cash)
        connection = await self._connect()
        try:
            for position in positions:
                price = marks.get(position["symbol"])
                if price is None:
                    await self._mark_position_stale(position, connection)
                    logger.warning(
                        f"Missing mark price for paper position {position['symbol']}; "
                        "equity excludes the stale position."
                    )
                    continue
                await self._mark_position_fresh(position, connection)
                sign = 1.0 if position.get("side", "buy").lower() in {"buy", "long"} else -1.0
                equity += (
                    sign
                    * float(position["quantity"])
                    * (float(price) - float(position["entry_price"]))
                )
            await connection.execute(
                "INSERT INTO equity_snapshots(equity, mark_prices, captured_at) VALUES (?, ?, ?)",
                (equity, json.dumps(marks, sort_keys=True), datetime.now(UTC).isoformat()),
            )
            await connection.commit()
        finally:
            await connection.close()
        return equity

    async def record_resolution(self, resolution: ResolutionRecord) -> bool:
        connection = await self._connect()
        try:
            await connection.execute(
                "INSERT INTO signal_resolutions(signal_id, symbol, timeframe, side, entry, stop, "
                "target, created_at_utc, resolved_at_utc, exit_price, exit_reason, candles_used, "
                "resolver_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    resolution.signal_id,
                    resolution.symbol,
                    resolution.timeframe,
                    resolution.side,
                    float(resolution.entry),
                    float(resolution.stop),
                    float(resolution.target),
                    resolution.utc_created_at().isoformat(),
                    resolution.utc_resolved_at().isoformat(),
                    None if resolution.exit_price is None else float(resolution.exit_price),
                    resolution.exit_reason,
                    int(resolution.candles_used),
                    resolution.resolver_version,
                ),
            )
            await connection.commit()
            return True
        except aiosqlite.IntegrityError as exc:
            if "UNIQUE constraint failed" not in str(exc):
                raise
            logger.debug(f"Duplicate resolution ignored for {resolution.signal_id}")
            return False
        finally:
            await connection.close()

    async def _mark_position_stale(
        self, position: dict[str, Any], connection: aiosqlite.Connection
    ) -> None:
        if position.get("id") is not None:
            await connection.execute(
                "UPDATE positions SET stale = 1, updated_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), int(position["id"])),
            )

    async def _mark_position_fresh(
        self, position: dict[str, Any], connection: aiosqlite.Connection
    ) -> None:
        if position.get("id") is not None:
            await connection.execute(
                "UPDATE positions SET stale = 0, updated_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), int(position["id"])),
            )

    async def close(self) -> None:
        return None
