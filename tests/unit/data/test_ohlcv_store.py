import pandas as pd
import pytest

from data.ohlcv_store import OhlcvStore


def _frame(rows: int, start: str = "2024-01-01", freq: str = "h", base: float = 100.0):
    index = pd.date_range(start, periods=rows, freq=freq, tz="UTC")
    values = [base + i for i in range(rows)]
    return pd.DataFrame(
        {
            "open": values,
            "high": [v + 1 for v in values],
            "low": [v - 1 for v in values],
            "close": [v + 0.5 for v in values],
            "volume": [1000.0 + i for i in range(rows)],
        },
        index=index,
    )


@pytest.fixture
async def store(tmp_path):
    instance = OhlcvStore(path=tmp_path / "ohlcv.db", max_rows_per_series=0)
    yield instance
    await instance.close()


async def test_overlapping_fetches_merge_into_one_series(store):
    await store.write_many("BTC/USDT", "1h", _frame(500))
    await store.write_many("BTC/USDT", "1h", _frame(1000))

    coverage = await store.coverage("BTC/USDT", "1h")
    assert coverage["rows"] == 1000

    frame = await store.read("BTC/USDT", "1h", 1000)
    assert len(frame) == 1000
    assert frame.index.is_unique


async def test_repeated_write_is_idempotent(store):
    frame = _frame(50)
    await store.write_many("ETH/USDT", "1h", frame)
    await store.write_many("ETH/USDT", "1h", frame)

    coverage = await store.coverage("ETH/USDT", "1h")
    assert coverage["rows"] == 50

    stored = await store.read("ETH/USDT", "1h", 50)
    assert stored["close"].iloc[-1] == pytest.approx(frame["close"].iloc[-1])


async def test_updated_candle_overwrites_the_old_row(store):
    await store.write_many("SOL/USDT", "1h", _frame(10))
    replacement = _frame(10)
    replacement.loc[replacement.index[-1], "close"] = 999.0

    await store.write_many("SOL/USDT", "1h", replacement)

    stored = await store.read("SOL/USDT", "1h", 10)
    assert stored["close"].iloc[-1] == pytest.approx(999.0)
    assert (await store.coverage("SOL/USDT", "1h"))["rows"] == 10


async def test_read_returns_most_recent_rows_in_ascending_order(store):
    await store.write_many("XRP/USDT", "1h", _frame(30))

    frame = await store.read("XRP/USDT", "1h", 10)

    assert len(frame) == 10
    assert frame.index.is_monotonic_increasing
    assert frame.index[-1] == _frame(30).index[-1]


async def test_read_missing_series_returns_none(store):
    assert await store.read("NOPE/USDT", "1h", 10) is None


async def test_rows_are_pruned_to_the_configured_maximum(tmp_path):
    instance = OhlcvStore(path=tmp_path / "ohlcv.db", max_rows_per_series=25)
    try:
        await instance.write_many("DOT/USDT", "1h", _frame(60))
        coverage = await instance.coverage("DOT/USDT", "1h")
        assert coverage["rows"] == 25

        frame = await instance.read("DOT/USDT", "1h", 100)
        assert frame.index[-1] == _frame(60).index[-1]
    finally:
        await instance.close()


async def test_empty_frame_is_ignored(store):
    assert await store.write_many("LTC/USDT", "1h", pd.DataFrame()) == 0
    assert await store.coverage("LTC/USDT", "1h") == {
        "rows": 0,
        "first_ts": None,
        "last_ts": None,
    }


async def test_frame_without_a_datetime_index_uses_the_timestamp_column(store):
    frame = _frame(5)
    frame.index.name = "timestamp"
    frame = frame.reset_index()
    frame["timestamp"] = (
        frame["timestamp"] - pd.Timestamp("1970-01-01", tz="UTC")
    ) // pd.Timedelta("1s")

    await store.write_many("LINK/USDT", "1h", frame)

    stored = await store.read("LINK/USDT", "1h", 5)
    assert len(stored) == 5
    assert isinstance(stored.index, pd.DatetimeIndex)
