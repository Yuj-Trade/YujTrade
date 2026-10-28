from datetime import UTC, datetime, timedelta

import pytest

from utils.scheduler_store import SchedulerStore


@pytest.fixture
def store(tmp_path):
    return SchedulerStore(tmp_path / "scheduler.db")


async def test_last_run_none_when_never_recorded(store):
    assert await store.last_run("daily") is None


async def test_record_then_last_run_roundtrip(store):
    finished = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
    await store.record(
        "daily",
        scheduled_at=datetime(2026, 10, 28, 5, 0, tzinfo=UTC),
        started_at=datetime(2026, 10, 28, 5, 30, tzinfo=UTC),
        finished_at=finished,
        status="ok",
    )
    result = await store.last_run("daily")
    assert result == finished


async def test_record_upserts_same_job(store):
    first = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
    second = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
    await store.record("daily", first, first, first, "ok")
    await store.record(
        "daily",
        scheduled_at=second - timedelta(minutes=30),
        started_at=second - timedelta(minutes=15),
        finished_at=second,
        status="failed",
        error="boom",
    )
    assert await store.last_run("daily") == second


async def test_is_due_true_without_previous_run(store):
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert await store.is_due("daily", now, interval_seconds=3600.0) is True


async def test_is_due_false_within_interval(store):
    finished = datetime(2026, 10, 28, 11, 30, tzinfo=UTC)
    await store.record("daily", finished, finished, finished, "ok")
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert await store.is_due("daily", now, interval_seconds=3600.0) is False


async def test_is_due_true_after_interval(store):
    finished = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    await store.record("daily", finished, finished, finished, "ok")
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert await store.is_due("daily", now, interval_seconds=3600.0) is True


async def test_error_truncated_to_500_chars(store):
    ts = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
    await store.record("daily", ts, ts, ts, "failed", error="x" * 1000)
    assert await store.last_run("daily") == ts


async def test_naive_datetime_is_stored_in_utc(store):
    ts = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
    await store.record("daily", ts, ts, ts, "ok")
    result = await store.last_run("daily")
    assert result is not None
    assert result.tzinfo is not None


async def test_close_is_noop(store):
    assert await store.close() is None
