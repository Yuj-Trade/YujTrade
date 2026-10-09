import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SchedulerStore:
    def __init__(self, path: str | Path = "runs/scheduler.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_runs (
                job_name TEXT PRIMARY KEY,
                scheduled_at TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self.connection.commit()

    def last_run(self, job_name: str) -> datetime | None:
        row = self.connection.execute(
            "SELECT finished_at FROM job_runs WHERE job_name = ?", (job_name,)
        ).fetchone()
        if not row or not row[0]:
            return None
        return datetime.fromisoformat(row[0])

    def is_due(self, job_name: str, now: datetime, interval_seconds: float) -> bool:
        previous = self.last_run(job_name)
        return previous is None or (now - previous).total_seconds() >= interval_seconds

    def record(
        self,
        job_name: str,
        scheduled_at: datetime,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        error: str = "",
    ) -> None:
        self.connection.execute(
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
                scheduled_at.astimezone(timezone.utc).isoformat(),
                started_at.astimezone(timezone.utc).isoformat(),
                finished_at.astimezone(timezone.utc).isoformat(),
                status,
                error[:500],
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
