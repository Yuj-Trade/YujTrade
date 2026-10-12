import sys

sys.path.insert(0, ".")

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

FIXED_END = pd.Timestamp("2025-01-01T00:00:00Z")
SEED = 20250101
CANDLES = 1500
REGIME_LENGTH = 150
REGIMES_1H = (
    ("up", 0.0025, 0.008),
    ("down", -0.0025, 0.008),
    ("range", 0.0, 0.012),
)
REGIMES_1D = (
    ("up", 0.009, 0.022),
    ("down", -0.009, 0.022),
    ("range", 0.0, 0.030),
)
FIXTURE_DIR = Path("tests/fixtures")


def _regime_returns(
    rng: np.random.Generator, periods: int, regimes: tuple = REGIMES_1H
) -> np.ndarray:
    chunks = []
    cycle = 0
    while sum(len(c) for c in chunks) < periods:
        name, drift, vol = regimes[cycle % len(regimes)]
        chunks.append(rng.normal(drift, vol, REGIME_LENGTH))
        cycle += 1
    return np.concatenate(chunks)[:periods]


def create_ohlcv_data(
    periods: int,
    freq: str,
    base_price: float,
    end: pd.Timestamp,
    seed: int,
    regimes: tuple = REGIMES_1H,
):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=end, periods=periods, freq=freq, tz="UTC")
    prices = base_price * np.exp(np.cumsum(_regime_returns(rng, periods, regimes)))
    opens = prices * (1 + rng.uniform(-0.002, 0.002, periods))
    highs = prices * (1 + rng.uniform(0, 0.005, periods))
    lows = prices * (1 - rng.uniform(0, 0.005, periods))
    volumes = rng.uniform(100, 10000, periods)
    frame = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": prices, "volume": volumes},
        index=dates,
    )
    frame["high"] = frame[["open", "high", "close"]].max(axis=1)
    frame["low"] = frame[["open", "low", "close"]].min(axis=1)
    return frame


def build_fixtures() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_1h = create_ohlcv_data(CANDLES, "1h", 50000.0, FIXED_END, SEED, REGIMES_1H)
    df_1d = create_ohlcv_data(CANDLES, "1D", 50000.0, FIXED_END.floor("1D"), SEED + 1, REGIMES_1D)
    return df_1h, df_1d


def from_warehouse(path: str, symbol: str = "BTC/USDT") -> tuple[pd.DataFrame, pd.DataFrame]:
    import sqlite3

    with sqlite3.connect(path) as conn:
        frames = {}
        for timeframe in ("1h", "1d"):
            frame = pd.read_sql_query(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol = ? AND timeframe = ? ORDER BY timestamp DESC LIMIT ?",
                conn,
                params=(symbol, timeframe, CANDLES),
            )
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
            frame = frame.sort_values("timestamp").set_index("timestamp")
            frames[timeframe] = frame
    return frames["1h"], frames["1d"]


def write_fixtures(df_1h: pd.DataFrame, df_1d: pd.DataFrame, out_dir: Path = FIXTURE_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in (("ohlcv_1h.csv", df_1h), ("ohlcv_1d.csv", df_1d)):
        frame.to_csv(out_dir / name, lineterminator="\n", float_format="%.10f")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic OHLCV fixtures")
    parser.add_argument("--from-warehouse", dest="warehouse", default=None)
    args = parser.parse_args(argv)
    if args.warehouse:
        df_1h, df_1d = from_warehouse(args.warehouse)
    else:
        df_1h, df_1d = build_fixtures()
    write_fixtures(df_1h, df_1d)
    print(f"1h rows={len(df_1h)} last={df_1h.index[-1]}")
    print(f"1d rows={len(df_1d)} last={df_1d.index[-1]}")


if __name__ == "__main__":
    main()
