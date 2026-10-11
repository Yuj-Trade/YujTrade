import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "create_fixtures", ROOT / "scripts/create_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixtures_are_byte_identical_across_runs(tmp_path):
    module = _load()
    first = tmp_path / "first"
    second = tmp_path / "second"
    for target in (first, second):
        df_1h, df_1d = module.build_fixtures()
        module.write_fixtures(df_1h, df_1d, target)
    for name in ("ohlcv_1h.csv", "ohlcv_1d.csv"):
        assert _sha256(first / name) == _sha256(second / name)


def test_fixtures_have_fixed_end_and_row_count(tmp_path):
    module = _load()
    df_1h, df_1d = module.build_fixtures()
    assert len(df_1h) == 1500
    assert len(df_1d) == 1500
    assert df_1h.index[-1] == pd.Timestamp("2025-01-01T00:00:00Z")
    assert df_1d.index[-1] == pd.Timestamp("2025-01-01T00:00:00Z")


def test_warehouse_option_reads_latest_candles(tmp_path):
    module = _load()
    db = tmp_path / "warehouse.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE ohlcv (symbol TEXT, timeframe TEXT, timestamp TEXT, "
            "open REAL, high REAL, low REAL, close REAL, volume REAL)"
        )
        rows = []
        for timeframe, freq in (("1h", "1h"), ("1d", "1D")):
            for i, ts in enumerate(pd.date_range("2024-01-01", periods=1600, freq=freq, tz="UTC")):
                price = 100.0 + i
                rows.append(
                    (
                        "BTC/USDT",
                        timeframe,
                        ts.isoformat(),
                        price,
                        price + 1,
                        price - 1,
                        price,
                        10.0,
                    )
                )
        conn.executemany("INSERT INTO ohlcv VALUES (?,?,?,?,?,?,?,?)", rows)
    frame_1h, frame_1d = module.from_warehouse(str(db))
    assert len(frame_1h) == 1500
    assert len(frame_1d) == 1500
    assert frame_1h.index.is_monotonic_increasing
