import json

from trading.ledger import PaperLedger


def _ledger(tmp_path):
    return PaperLedger(tmp_path / "paper_ledger.db")


def test_duplicate_signal_id_is_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    first = ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0)
    second = ledger.append_order("sig-1", "BTC/USDT", "buy", 2.0)
    assert isinstance(first, int)
    assert second is None
    rows = ledger.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert rows == 1
    ledger.close()


def test_equity_uses_mark_price_not_entry(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.connection.execute(
        "INSERT INTO positions(symbol, side, quantity, entry_price) VALUES (?, ?, ?, ?)",
        ("BTC/USDT", "buy", 1.0, 100.0),
    )
    positions = [
        {"id": 1, "symbol": "BTC/USDT", "side": "buy", "quantity": 1.0, "entry_price": 100.0}
    ]
    equity = ledger.snapshot_equity(9000.0, positions, {"BTC/USDT": 110.0})
    assert equity == 9010.0
    stored = ledger.connection.execute(
        "SELECT equity, mark_prices FROM equity_snapshots"
    ).fetchone()
    assert stored["equity"] == 9010.0
    assert json.loads(stored["mark_prices"]) == {"BTC/USDT": 110.0}
    ledger.close()


def test_missing_mark_price_excludes_position_and_marks_stale(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.connection.execute(
        "INSERT INTO positions(symbol, side, quantity, entry_price) VALUES (?, ?, ?, ?)",
        ("ETH/USDT", "buy", 5.0, 200.0),
    )
    positions = [
        {"id": 1, "symbol": "ETH/USDT", "side": "buy", "quantity": 5.0, "entry_price": 200.0}
    ]
    equity = ledger.snapshot_equity(9000.0, positions, {})
    assert equity == 9000.0
    stale = ledger.connection.execute("SELECT stale FROM positions WHERE id = 1").fetchone()[0]
    assert stale == 1
    ledger.close()
