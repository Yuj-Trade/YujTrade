from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_runs (
    job_name TEXT PRIMARY KEY,
    scheduled_at TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT ''
)
"""


class SchedulerStore:
    def __init__(self, path: str | Path = "runs/scheduler.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def _connect(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self.path)
        await connection.execute(_SCHEMA)
        return connection

    async def last_run(self, job_name: str) -> datetime | None:
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                "SELECT finished_at FROM job_runs WHERE job_name = ?", (job_name,)
            )
            row = await cursor.fetchone()
        finally:
            await connection.close()
        if not row or not row[0]:
            return None
        return datetime.fromisoformat(row[0])

    async def is_due(self, job_name: str, now: datetime, interval_seconds: float) -> bool:
        previous = await self.last_run(job_name)
        return previous is None or (now - previous).total_seconds() >= interval_seconds

    async def record(
        self,
        job_name: str,
        scheduled_at: datetime,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        error: str = "",
    ) -> None:
        connection = await self._connect()
        try:
            await connection.execute(
                """
                INSERT INTO job_runs(job_name, scheduled_at, started_at, finished_at, status, error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_name) DO UPDATE SET
                    scheduled_at=excluded.scheduled_at,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    status=excluded.status,
                    error=excluded.error
                """,
                (
                    job_name,
                    scheduled_at.astimezone(UTC).isoformat(),
                    started_at.astimezone(UTC).isoformat(),
                    finished_at.astimezone(UTC).isoformat(),
                    status,
                    error[:500],
                ),
            )
            await connection.commit()
        finally:
            await connection.close()

    async def close(self) -> None:
        return None
