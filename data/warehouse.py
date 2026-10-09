import sqlite3
from pathlib import Path
from typing import Iterable


class IndicatorHistoryWarehouse:
    def __init__(self, path: str | Path = "runs/indicator_history.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS indicator_history (
                name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY(name, timestamp)
            )
            """
        )
        self.connection.commit()

    def write(self, name: str, timestamp: str, value: float) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO indicator_history(name, timestamp, value) VALUES (?, ?, ?)",
            (name, timestamp, float(value)),
        )
        self.connection.commit()

    def read(self, names: Iterable[str], limit: int = 500) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {}
        for name in names:
            rows = self.connection.execute(
                """
                SELECT value FROM indicator_history
                WHERE name = ? ORDER BY timestamp DESC LIMIT ?
                """,
                (name, int(limit)),
            ).fetchall()
            result[name] = [float(row[0]) for row in reversed(rows)]
        return result

    def close(self) -> None:
        self.connection.close()
