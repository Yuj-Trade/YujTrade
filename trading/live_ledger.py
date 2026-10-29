from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from config.logger import logger
from domain.exchange_types import (
    NON_TERMINAL_STATUSES,
    PENDING_SUBMIT,
    SHADOW,
    TERMINAL_STATUSES,
    OrderIntent,
    OrderSnapshot,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    exchange_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    exchange_order_id TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    amount REAL NOT NULL,
    price REAL NOT NULL,
    filled REAL NOT NULL DEFAULT 0,
    average_price REAL NOT NULL DEFAULT 0,
    fee_cost REAL NOT NULL DEFAULT 0,
    fee_currency TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('sandbox', 'live', 'shadow')),
    reason TEXT NOT NULL DEFAULT '',
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE (exchange_id, client_order_id)
);
CREATE TABLE IF NOT EXISTS live_control (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);
"""

_COLUMNS = (
    "signal_id, exchange_id, client_order_id, exchange_order_id, symbol, side, amount, price, "
    "filled, average_price, fee_cost, fee_currency, status, mode, reason, created_at_utc, "
    "updated_at_utc"
)

_NON_TERMINAL_SQL = ", ".join(f"'{status}'" for status in sorted(NON_TERMINAL_STATUSES))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = [column.strip() for column in _COLUMNS.split(",")]
    return dict(zip(keys, row, strict=True))


class LiveLedger:
    def __init__(self, path: str | Path = "runs/live_ledger.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def _connect(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self.path, timeout=30.0)
        await connection.execute("PRAGMA journal_mode=WAL")
        return connection

    async def initialize(self) -> None:
        connection = await self._connect()
        try:
            await connection.executescript(_SCHEMA)
            await connection.commit()
        finally:
            await connection.close()

    async def append_pending(self, intent: OrderIntent, mode: str, reason: str = "") -> bool:
        status = SHADOW if mode == "shadow" else PENDING_SUBMIT
        moment = _now_iso()
        connection = await self._connect()
        try:
            await connection.execute(
                "INSERT INTO live_orders(signal_id, exchange_id, client_order_id, symbol, side, "
                "amount, price, status, mode, reason, created_at_utc, updated_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    intent.signal_id,
                    intent.exchange_id,
                    intent.client_order_id,
                    intent.symbol,
                    intent.side,
                    float(intent.amount),
                    float(intent.price),
                    status,
                    mode,
                    reason,
                    moment,
                    moment,
                ),
            )
            await connection.commit()
            return True
        except aiosqlite.IntegrityError:
            logger.warning(
                f"Duplicate live order refused for {intent.exchange_id}/{intent.signal_id}"
            )
            return False
        finally:
            await connection.close()

    async def _current_status(
        self, connection: aiosqlite.Connection, client_order_id: str, exchange_id: str
    ) -> str | None:
        cursor = await connection.execute(
            "SELECT status FROM live_orders WHERE client_order_id = ? AND exchange_id = ?",
            (client_order_id, exchange_id),
        )
        row = await cursor.fetchone()
        return None if row is None else str(row[0])

    async def update_from_snapshot(
        self, client_order_id: str, exchange_id: str, snapshot: OrderSnapshot
    ) -> bool:
        connection = await self._connect()
        try:
            current = await self._current_status(connection, client_order_id, exchange_id)
            if current is None:
                return False
            if current in TERMINAL_STATUSES:
                return False
            await connection.execute(
                "UPDATE live_orders SET exchange_order_id = ?, status = ?, filled = ?, "
                "average_price = ?, fee_cost = ?, fee_currency = ?, updated_at_utc = ? "
                "WHERE client_order_id = ? AND exchange_id = ?",
                (
                    snapshot.exchange_order_id,
                    snapshot.status,
                    float(snapshot.filled),
                    float(snapshot.average_price),
                    float(snapshot.fee_cost),
                    snapshot.fee_currency,
                    _now_iso(),
                    client_order_id,
                    exchange_id,
                ),
            )
            await connection.commit()
            return True
        finally:
            await connection.close()

    async def set_status(
        self, client_order_id: str, exchange_id: str, status: str, reason: str = ""
    ) -> bool:
        connection = await self._connect()
        try:
            current = await self._current_status(connection, client_order_id, exchange_id)
            if current is None:
                return False
            if current in TERMINAL_STATUSES:
                return False
            await connection.execute(
                "UPDATE live_orders SET status = ?, reason = ?, updated_at_utc = ? "
                "WHERE client_order_id = ? AND exchange_id = ?",
                (status, reason, _now_iso(), client_order_id, exchange_id),
            )
            await connection.commit()
            return True
        finally:
            await connection.close()

    async def set_exchange_order_id(
        self, client_order_id: str, exchange_id: str, exchange_order_id: str
    ) -> bool:
        connection = await self._connect()
        try:
            await connection.execute(
                "UPDATE live_orders SET exchange_order_id = ?, updated_at_utc = ? "
                "WHERE client_order_id = ? AND exchange_id = ?",
                (exchange_order_id, _now_iso(), client_order_id, exchange_id),
            )
            await connection.commit()
            return True
        finally:
            await connection.close()

    async def get_row(self, client_order_id: str, exchange_id: str) -> dict[str, Any] | None:
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM live_orders WHERE client_order_id = ? AND exchange_id = ?",
                (client_order_id, exchange_id),
            )
            row = await cursor.fetchone()
            return None if row is None else _row_to_dict(row)
        finally:
            await connection.close()

    async def get_non_terminal(self, exchange_id: str | None = None) -> list[dict[str, Any]]:
        connection = await self._connect()
        try:
            query = f"SELECT {_COLUMNS} FROM live_orders WHERE status IN ({_NON_TERMINAL_SQL})"
            params: tuple[Any, ...] = ()
            if exchange_id is not None:
                query += " AND exchange_id = ?"
                params = (exchange_id,)
            query += " ORDER BY id"
            cursor = await connection.execute(query, params)
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            await connection.close()

    async def get_shadow_rows(self) -> list[dict[str, Any]]:
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                f"SELECT {_COLUMNS} FROM live_orders WHERE mode = 'shadow' ORDER BY id"
            )
            rows = await cursor.fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            await connection.close()

    async def daily_notional(self, exchange_id: str, day_utc: date | str) -> float:
        day = day_utc.isoformat() if isinstance(day_utc, date) else str(day_utc)
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                "SELECT COALESCE(SUM(amount * price), 0.0) FROM live_orders "
                "WHERE exchange_id = ? AND mode IN ('sandbox', 'live') "
                "AND status != 'rejected' AND substr(created_at_utc, 1, 10) = ?",
                (exchange_id, day),
            )
            row = await cursor.fetchone()
            return float(row[0]) if row else 0.0
        finally:
            await connection.close()

    async def set_control(self, key: str, value: str) -> None:
        connection = await self._connect()
        try:
            await connection.execute(
                "INSERT INTO live_control(key, value, updated_at_utc) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at_utc = excluded.updated_at_utc",
                (key, str(value), _now_iso()),
            )
            await connection.commit()
        finally:
            await connection.close()

    async def get_control(self, key: str, default: str = "") -> str:
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                "SELECT value FROM live_control WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            return default if row is None else str(row[0])
        finally:
            await connection.close()

    async def close(self) -> None:
        return None
