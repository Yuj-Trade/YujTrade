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
        resolved_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
        exit_price=exit_price,
        exit_reason=exit_reason,
        candles_used=4,
        resolver_version="v1",
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


async def test_timestamps_are_stored_as_utc_iso_strings(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    await ledger.record_resolution(_record())
    stored = await _scalar(db, "SELECT resolved_at_utc FROM signal_resolutions")
    assert stored == "2026-10-01T14:00:00+00:00"


async def test_no_data_resolution_stores_null_exit_price(tmp_path):
    db = tmp_path / "paper_ledger.db"
    ledger = PaperLedger(db)
    record = _record(exit_price=None, exit_reason="no_data")
    assert await ledger.record_resolution(record) is True
    assert await _scalar(db, "SELECT exit_price FROM signal_resolutions") is None


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
                "target, created_at_utc, resolved_at_utc, exit_price, exit_reason, candles_used, "
                "resolver_version) VALUES ('raw', 'BTC/USDT', '1h', 'buy', 100, 90, 120, "
                "'2026-10-01T10:00:00+00:00', '2026-10-01T14:00:00+00:00', NULL, 'stop', 4, 'v1')"
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
        exit_price=None,
        exit_reason="stop",
        candles_used=4,
        resolver_version="v1",
        utc_created_at=lambda: datetime(2026, 10, 1, 10, tzinfo=UTC),
        utc_resolved_at=lambda: datetime(2026, 10, 1, 14, tzinfo=UTC),
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
