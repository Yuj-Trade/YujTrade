import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from config.logger import logger

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
