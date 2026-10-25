import asyncio

import pytest

from utils.background_manager import BackgroundTaskManager


async def _return_after(value, delay=0.01):
    await asyncio.sleep(delay)
    return value


async def test_create_task_registers_and_completes_the_task():
    manager = BackgroundTaskManager()

    task = manager.create_task(_return_after("done"), name="probe")

    assert task.get_name() == "probe"
    assert manager._tasks == {task}

    await task
    await asyncio.sleep(0)

    assert await task == "done"
    assert manager._tasks == set()


async def test_a_failing_task_is_removed_and_does_not_propagate():
    manager = BackgroundTaskManager()

    async def boom():
        raise RuntimeError("exploded")

    task = manager.create_task(boom(), name="boom")
    await asyncio.sleep(0.05)

    assert manager._tasks == set()
    assert task.done()
    with pytest.raises(RuntimeError):
        task.result()


async def test_cancelled_task_is_removed():
    manager = BackgroundTaskManager()

    task = manager.create_task(_return_after("late", delay=10), name="slow")
    task.cancel()
    await asyncio.sleep(0.05)

    assert manager._tasks == set()
    assert task.cancelled()


async def test_cancel_all_cancels_every_tracked_task():
    manager = BackgroundTaskManager()
    first = manager.create_task(_return_after("a", delay=10), name="a")
    second = manager.create_task(_return_after("b", delay=10), name="b")

    await manager.cancel_all()

    assert first.cancelled()
    assert second.cancelled()
    assert manager._tasks == set()


async def test_cancel_all_without_tasks_is_a_no_op():
    manager = BackgroundTaskManager()

    await manager.cancel_all()

    assert manager._tasks == set()


async def test_completed_tasks_are_not_cancelled_again():
    manager = BackgroundTaskManager()
    task = manager.create_task(_return_after("done"), name="done")
    await task
    await asyncio.sleep(0)

    await manager.cancel_all()

    assert task.result() == "done"
    assert manager._tasks == set()


async def test_tasks_run_concurrently():
    manager = BackgroundTaskManager()
    order: list[str] = []

    async def job(name, delay):
        await asyncio.sleep(delay)
        order.append(name)

    manager.create_task(job("slow", 0.05), name="slow")
    manager.create_task(job("fast", 0.01), name="fast")
    await asyncio.sleep(0.1)

    assert order == ["fast", "slow"]
    assert manager._tasks == set()
