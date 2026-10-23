from datetime import UTC, datetime, timedelta

from data.warehouse import IndicatorHistoryWarehouse
from utils.scheduler_store import SchedulerStore


async def test_warehouse_write_read_round_trip(tmp_path):
    store = IndicatorHistoryWarehouse(tmp_path / "history.db")
    await store.write("rsi", "2025-01-01T00:00:00+00:00", 55.5)
    assert await store.read(["rsi"], 500) == {"rsi": [55.5]}


async def test_warehouse_write_many_batches_in_one_call(tmp_path):
    store = IndicatorHistoryWarehouse(tmp_path / "history.db")
    rows = [(f"ind{i}", "2025-01-01T00:00:00+00:00", float(i)) for i in range(5)]
    await store.write_many(rows)
    history = await store.read([f"ind{i}" for i in range(5)], 500)
    assert history == {f"ind{i}": [float(i)] for i in range(5)}


async def test_warehouse_read_orders_by_timestamp_desc_limit(tmp_path):
    store = IndicatorHistoryWarehouse(tmp_path / "history.db")
    await store.write_many(
        [
            ("rsi", "2025-01-03T00:00:00+00:00", 3.0),
            ("rsi", "2025-01-01T00:00:00+00:00", 1.0),
            ("rsi", "2025-01-02T00:00:00+00:00", 2.0),
        ]
    )
    assert await store.read(["rsi"], 2) == {"rsi": [2.0, 3.0]}


async def test_warehouse_close_is_idempotent(tmp_path):
    store = IndicatorHistoryWarehouse(tmp_path / "history.db")
    await store.close()
    await store.close()


async def test_scheduler_store_record_and_due_cycle(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.db")
    now = datetime.now(UTC)
    assert await store.is_due("job", now, 3600.0) is True
    await store.record("job", now, now, now, "success")
    assert await store.last_run("job") == now
    assert await store.is_due("job", now, 3600.0) is False
    assert await store.is_due("job", now + timedelta(hours=2), 3600.0) is True


async def test_scheduler_store_close_is_idempotent(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.db")
    await store.close()
    await store.close()


def test_warehouse_and_schedulerExpose_coroutines():
    import inspect

    assert inspect.iscoroutinefunction(IndicatorHistoryWarehouse.read)
    assert inspect.iscoroutinefunction(IndicatorHistoryWarehouse.write_many)
    assert inspect.iscoroutinefunction(SchedulerStore.is_due)
    assert inspect.iscoroutinefunction(SchedulerStore.record)


async def test_warehouse_concurrent_writes_and_reads_do_not_lock(tmp_path):
    import asyncio

    store = IndicatorHistoryWarehouse(tmp_path / "history.db")

    async def _write(idx: int):
        rows = [
            (f"conc{idx}", f"2025-01-01T00:00:{row:02d}+00:00", float(row)) for row in range(50)
        ]
        await store.write_many(rows)

    async def _read(idx: int):
        return await store.read([f"conc{idx}"], 500)

    tasks = [_write(i) for i in range(200)] + [_read(i) for i in range(200)]
    await asyncio.gather(*tasks)

    for idx in range(200):
        history = await store.read([f"conc{idx}"], 500)
        assert len(history[f"conc{idx}"]) == 50
