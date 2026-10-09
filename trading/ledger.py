import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class PaperLedger:
    def __init__(self, path: str | Path = "runs/paper_ledger.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
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
                stale INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equity REAL NOT NULL,
                mark_prices TEXT NOT NULL,
                captured_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def append_order(
        self, signal_id: str, symbol: str, side: str, quantity: float
    ) -> int | None:
        try:
            cursor = self.connection.execute(
                "INSERT INTO orders(signal_id, symbol, side, quantity, created_at) VALUES (?, ?, ?, ?, ?)",
                (signal_id, symbol, side, float(quantity), datetime.now(timezone.utc).isoformat()),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def snapshot_equity(self, cash: float, positions: Iterable[dict[str, Any]], marks: dict[str, float]) -> float:
        equity = float(cash)
        stale = []
        for position in positions:
            price = marks.get(position["symbol"])
            if price is None:
                stale.append(position["symbol"])
                price = position["entry_price"]
            sign = 1.0 if position.get("side", "buy").lower() in {"buy", "long"} else -1.0
            equity += sign * float(position["quantity"]) * (float(price) - float(position["entry_price"]))
        self.connection.execute(
            "INSERT INTO equity_snapshots(equity, mark_prices, captured_at) VALUES (?, ?, ?)",
            (equity, repr(marks), datetime.now(timezone.utc).isoformat()),
        )
        self.connection.commit()
        return equity

    def close(self) -> None:
        self.connection.close()
