from datetime import UTC, datetime
from types import SimpleNamespace

import aiosqlite
import pytest

from domain.performance import ResolutionRecord
from trading.ledger import PaperLedger


def _record(
    signal_id: str = "sig-1",
    exit_price: float | None = 120.0,
    exit_reason: str = "target",
    exit_at: datetime | None = datetime(2026, 10, 1, 14, tzinfo=UTC),
) -> ResolutionRecord:
    return ResolutionRecord(
        signal_id=signal_id,
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        entry=100.0,
        stop=90.0,
        target=120.0,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        exit_at=exit_at,
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="paper-resolution-v1",
    )


async def _scalar(path, sql: str, params: tuple = ()):
    async with aiosqlite.connect(path) as connection:
        cursor = await connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0]


async def test_first_insert_is_recorded_and_returns_true(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    assert await ledger.record_resolution(_record()) is True
    assert await _scalar(db, "SELECT COUNT(*) FROM signal_resolutions") == 1


async def test_duplicate_signal_returns_false_and_keeps_original(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    assert await ledger.record_resolution(_record(exit_price=120.0)) is True
    assert await ledger.record_resolution(_record(exit_price=95.0, exit_reason="stop")) is False
    assert await _scalar(db, "SELECT COUNT(*) FROM signal_resolutions") == 1
    assert await _scalar(db, "SELECT exit_price FROM signal_resolutions") == pytest.approx(120.0)


async def test_timestamps_are_stored_as_utc_iso_strings_with_microseconds(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record())
    created = await _scalar(db, "SELECT created_at_utc FROM signal_resolutions")
    resolved = await _scalar(db, "SELECT exit_at_utc FROM signal_resolutions")
    assert created == "2026-10-01T10:00:00.000000+00:00"
    assert resolved == "2026-10-01T14:00:00.000000+00:00"


async def test_recorded_at_utc_is_written_on_every_row(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record())
    recorded = await _scalar(db, "SELECT recorded_at_utc FROM signal_resolutions")
    assert recorded.endswith("+00:00")
    assert "." in recorded


async def test_no_data_resolution_stores_null_exit_price_and_exit_time(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    record = _record(exit_price=None, exit_reason="no_data", exit_at=None)
    assert await ledger.record_resolution(record) is True
    assert await _scalar(db, "SELECT exit_price FROM signal_resolutions") is None
    assert await _scalar(db, "SELECT exit_at_utc FROM signal_resolutions") is None


async def test_update_on_resolution_is_rejected(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record())
    async with aiosqlite.connect(db) as connection:
        with pytest.raises(aiosqlite.IntegrityError, match="append-only"):
            await connection.execute("UPDATE signal_resolutions SET exit_price = 1.0")
            await connection.commit()


async def test_delete_on_resolution_is_rejected(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record())
    async with aiosqlite.connect(db) as connection:
        with pytest.raises(aiosqlite.IntegrityError, match="append-only"):
            await connection.execute("DELETE FROM signal_resolutions")
            await connection.commit()


async def test_check_constraint_rejects_inconsistent_raw_row(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.initialize()
    async with aiosqlite.connect(db) as connection:
        with pytest.raises(aiosqlite.IntegrityError, match="CHECK"):
            await connection.execute(
                "INSERT INTO signal_resolutions(signal_id, symbol, timeframe, side, entry, stop, "
                "target, created_at_utc, exit_at_utc, exit_price, exit_reason, candles_used, "
                "resolver_version, recorded_at_utc) VALUES ('raw', 'BTC/USDT', '1h', 'buy', 100, "
                "90, 120, '2026-10-01T10:00:00.000000+00:00', "
                "'2026-10-01T14:00:00.000000+00:00', NULL, 'stop', 4, 'v1', "
                "'2026-10-01T14:00:00.000000+00:00')"
            )


async def test_side_check_constraint_rejects_an_unknown_side(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.initialize()
    async with aiosqlite.connect(db) as connection:
        with pytest.raises(aiosqlite.IntegrityError, match="CHECK"):
            await connection.execute(
                "INSERT INTO signal_resolutions(signal_id, symbol, timeframe, side, entry, stop, "
                "target, created_at_utc, exit_at_utc, exit_price, exit_reason, candles_used, "
                "resolver_version, recorded_at_utc) VALUES ('raw', 'BTC/USDT', '1h', 'long', 100, "
                "90, 120, '2026-10-01T10:00:00.000000+00:00', "
                "'2026-10-01T14:00:00.000000+00:00', 120, 'target', 4, 'v1', "
                "'2026-10-01T14:00:00.000000+00:00')"
            )


async def test_non_unique_integrity_error_propagates(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.initialize()
    inconsistent = SimpleNamespace(
        signal_id="sig-bad",
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        entry=100.0,
        stop=90.0,
        target=120.0,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
        exit_price=None,
        exit_reason="stop",
        candles_used=4,
        resolver_version="v1",
    )
    with pytest.raises(aiosqlite.IntegrityError, match="CHECK"):
        await ledger.record_resolution(inconsistent)
    assert await _scalar(db, "SELECT COUNT(*) FROM signal_resolutions") == 0


async def test_initialize_is_idempotent_and_keeps_existing_rows(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record())
    await ledger.initialize()
    await ledger.initialize()
    assert await _scalar(db, "SELECT COUNT(*) FROM signal_resolutions") == 1


async def test_existing_order_path_is_unaffected(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    assert await ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0) == 1
    assert await ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0) is None
    assert await _scalar(db, "SELECT COUNT(*) FROM orders") == 1


async def test_has_resolution_reports_the_presence_of_a_row(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    assert await ledger.has_resolution("sig-1") is False
    await ledger.record_resolution(_record())
    assert await ledger.has_resolution("sig-1") is True
    assert await ledger.has_resolution("sig-2") is False


async def test_load_resolutions_returns_the_range_ordered_by_exit_then_signal_id(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(
        _record(signal_id="sig-b", exit_at=datetime(2026, 10, 1, 12, tzinfo=UTC))
    )
    await ledger.record_resolution(
        _record(signal_id="sig-a", exit_at=datetime(2026, 10, 1, 12, tzinfo=UTC))
    )
    await ledger.record_resolution(
        _record(signal_id="sig-c", exit_at=datetime(2026, 10, 1, 11, tzinfo=UTC))
    )

    loaded = await ledger.load_resolutions(
        datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
    )

    assert [record.signal_id for record in loaded] == ["sig-c", "sig-a", "sig-b"]


async def test_load_resolutions_returns_the_no_data_rows_too(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(
        _record(signal_id="sig-nd", exit_price=None, exit_reason="no_data", exit_at=None)
    )

    loaded = await ledger.load_resolutions(
        datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
    )

    assert len(loaded) == 1
    assert loaded[0].exit_reason == "no_data"
    assert loaded[0].exit_price is None
    assert loaded[0].exit_at is None


async def test_load_resolutions_excludes_rows_outside_the_range(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record(signal_id="old"))

    loaded = await ledger.load_resolutions(
        datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC)
    )

    assert loaded == []


async def test_loaded_records_round_trip_their_fields(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record())

    loaded = await ledger.load_resolutions(
        datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
    )

    assert len(loaded) == 1
    stored = loaded[0]
    assert stored.signal_id == "sig-1"
    assert stored.symbol == "BTC/USDT"
    assert stored.timeframe == "1h"
    assert stored.side == "buy"
    assert stored.entry == pytest.approx(100.0)
    assert stored.stop == pytest.approx(90.0)
    assert stored.target == pytest.approx(120.0)
    assert stored.exit_price == pytest.approx(120.0)
    assert stored.exit_reason == "target"
    assert stored.candles_used == 4
    assert stored.resolver_version == "paper-resolution-v1"
    assert stored.created_at == datetime(2026, 10, 1, 10, tzinfo=UTC)
    assert stored.exit_at == datetime(2026, 10, 1, 14, tzinfo=UTC)
