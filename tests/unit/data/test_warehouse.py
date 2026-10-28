import pytest

from data.warehouse import IndicatorHistoryWarehouse


@pytest.fixture
def warehouse(tmp_path):
    return IndicatorHistoryWarehouse(tmp_path / "indicator_history.db")


async def test_write_then_read_single(warehouse):
    await warehouse.write("rsi", "2026-01-01T00:00:00", 55.5)
    result = await warehouse.read(["rsi"])
    assert result["rsi"] == [55.5]


async def test_read_orders_oldest_to_newest(warehouse):
    await warehouse.write("rsi", "2026-01-03T00:00:00", 3.0)
    await warehouse.write("rsi", "2026-01-01T00:00:00", 1.0)
    await warehouse.write("rsi", "2026-01-02T00:00:00", 2.0)
    result = await warehouse.read(["rsi"])
    assert result["rsi"] == [1.0, 2.0, 3.0]


async def test_write_many_replaces_duplicate_keys(warehouse):
    await warehouse.write("rsi", "2026-01-01T00:00:00", 1.0)
    await warehouse.write_many(
        [
            ("rsi", "2026-01-01T00:00:00", 9.0),
            ("rsi", "2026-01-02T00:00:00", 2.0),
        ]
    )
    result = await warehouse.read(["rsi"])
    assert result["rsi"] == [9.0, 2.0]


async def test_write_many_empty_is_noop(warehouse):
    await warehouse.write_many([])
    result = await warehouse.read(["rsi"])
    assert result["rsi"] == []


async def test_read_limit_returns_latest(warehouse):
    await warehouse.write_many(
        [(  "atr", f"2026-01-{day:02d}T00:00:00", float(day)) for day in range(1, 6)]
    )
    result = await warehouse.read(["atr"], limit=2)
    assert result["atr"] == [4.0, 5.0]


async def test_read_unknown_name_empty_list(warehouse):
    result = await warehouse.read(["missing"])
    assert result["missing"] == []


async def test_read_multiple_names(warehouse):
    await warehouse.write("rsi", "2026-01-01T00:00:00", 1.0)
    await warehouse.write("macd", "2026-01-01T00:00:00", 2.0)
    result = await warehouse.read(["rsi", "macd"])
    assert result["rsi"] == [1.0]
    assert result["macd"] == [2.0]


async def test_close_is_noop(warehouse):
    assert await warehouse.close() is None
