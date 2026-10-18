import json

import aiosqlite

from trading.ledger import PaperLedger


def _ledger(tmp_path):
    return PaperLedger(tmp_path / "paper_ledger.db")


async def _count_rows(db_path, table):
    async with aiosqlite.connect(db_path) as connection:
        cursor = await connection.execute(f"SELECT COUNT(*) FROM {table}")
        row = await cursor.fetchone()
        return int(row[0])


async def _fetch_one(db_path, query, params=()):
    async with aiosqlite.connect(db_path) as connection:
        cursor = await connection.execute(query, params)
        return await cursor.fetchone()


async def _insert_position(db_path, symbol, side, quantity, entry_price):
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute(
            "INSERT INTO positions(symbol, side, quantity, entry_price) VALUES (?, ?, ?, ?)",
            (symbol, side, quantity, entry_price),
        )
        await connection.commit()


async def test_duplicate_signal_id_is_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    first = await ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0)
    second = await ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0)
    assert isinstance(first, int)
    assert second is None
    assert await _count_rows(tmp_path / "paper_ledger.db", "orders") == 1


async def test_concurrent_appends_of_distinct_ids_both_land(tmp_path):
    ledger = _ledger(tmp_path)
    results = []
    results.append(await ledger.append_order("sig-a", "BTC/USDT", "buy", 1.0))
    results.append(await ledger.append_order("sig-b", "ETH/USDT", "buy", 2.0))
    assert all(isinstance(order_id, int) for order_id in results)
    assert await _count_rows(tmp_path / "paper_ledger.db", "orders") == 2


async def test_equity_uses_mark_price_not_entry(tmp_path):
    ledger = _ledger(tmp_path)
    await ledger.initialize()
    await _insert_position(tmp_path / "paper_ledger.db", "BTC/USDT", "buy", 1.0, 100.0)
    positions = [
        {"id": 1, "symbol": "BTC/USDT", "side": "buy", "quantity": 1.0, "entry_price": 100.0}
    ]
    equity = await ledger.snapshot_equity(9000.0, positions, {"BTC/USDT": 110.0})
    assert equity == 9010.0
    stored = await _fetch_one(
        tmp_path / "paper_ledger.db", "SELECT equity, mark_prices FROM equity_snapshots"
    )
    assert stored[0] == 9010.0
    assert json.loads(stored[1]) == {"BTC/USDT": 110.0}


async def test_missing_mark_price_excludes_position_and_marks_stale(tmp_path):
    ledger = _ledger(tmp_path)
    await ledger.initialize()
    await _insert_position(tmp_path / "paper_ledger.db", "ETH/USDT", "buy", 5.0, 200.0)
    positions = [
        {"id": 1, "symbol": "ETH/USDT", "side": "buy", "quantity": 5.0, "entry_price": 200.0}
    ]
    equity = await ledger.snapshot_equity(9000.0, positions, {})
    assert equity == 9000.0
    stale = await _fetch_one(
        tmp_path / "paper_ledger.db", "SELECT stale FROM positions WHERE id = 1"
    )
    assert stale[0] == 1
