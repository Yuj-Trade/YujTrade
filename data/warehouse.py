from collections.abc import Iterable
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS indicator_history (
    name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY(name, timestamp)
)
"""


class IndicatorHistoryWarehouse:
    def __init__(self, path: str | Path = "runs/indicator_history.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def _connect(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self.path)
        await connection.execute(_SCHEMA)
        return connection

    async def write(self, name: str, timestamp: str, value: float) -> None:
        await self.write_many([(name, timestamp, value)])

    async def write_many(self, rows: list[tuple[str, str, float]]) -> None:
        if not rows:
            return
        connection = await self._connect()
        try:
            await connection.executemany(
                "INSERT OR REPLACE INTO indicator_history(name, timestamp, value) VALUES (?, ?, ?)",
                [(name, timestamp, float(value)) for name, timestamp, value in rows],
            )
            await connection.commit()
        finally:
            await connection.close()

    async def read(self, names: Iterable[str], limit: int = 500) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {}
        connection = await self._connect()
        try:
            for name in names:
                cursor = await connection.execute(
                    """
                    SELECT value FROM indicator_history
                    WHERE name = ? ORDER BY timestamp DESC LIMIT ?
                    """,
                    (name, int(limit)),
                )
                rows = await cursor.fetchall()
                result[name] = [float(row[0]) for row in reversed(rows)]
        finally:
            await connection.close()
        return result

    async def close(self) -> None:
        return None
