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
WALK_FORWARD_CANDLES = 900
WALK_FORWARD_SEED = 20250202
WALK_FORWARD_BASE_PRICE = 42000.0
DRIFT_CANDLES = 1200
DRIFT_SEED = 20250303
DRIFT_BASE_PRICE = 30000.0
DRIFT_STABLE_DRIFT = 0.0004
DRIFT_STABLE_VOL = 0.003
DRIFT_SHIFTED_DRIFT = 0.005
DRIFT_SHIFTED_VOL = 0.014


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


def build_walk_forward_fixture() -> pd.DataFrame:
    return create_ohlcv_data(
        WALK_FORWARD_CANDLES,
        "1h",
        WALK_FORWARD_BASE_PRICE,
        FIXED_END,
        WALK_FORWARD_SEED,
        REGIMES_1H,
    )


def build_drift_fixture(shifted: bool) -> pd.DataFrame:
    rng = np.random.default_rng(DRIFT_SEED)
    half = DRIFT_CANDLES // 2
    returns = rng.normal(DRIFT_STABLE_DRIFT, DRIFT_STABLE_VOL, DRIFT_CANDLES)
    if shifted:
        returns[half:] = rng.normal(DRIFT_SHIFTED_DRIFT, DRIFT_SHIFTED_VOL, DRIFT_CANDLES - half)
    dates = pd.date_range(end=FIXED_END, periods=DRIFT_CANDLES, freq="1h", tz="UTC")
    prices = DRIFT_BASE_PRICE * np.exp(np.cumsum(returns))
    opens = prices * (1 + rng.uniform(-0.002, 0.002, DRIFT_CANDLES))
    highs = prices * (1 + rng.uniform(0, 0.005, DRIFT_CANDLES))
    lows = prices * (1 - rng.uniform(0, 0.005, DRIFT_CANDLES))
    volumes = rng.uniform(100, 10000, DRIFT_CANDLES)
    frame = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": prices, "volume": volumes},
        index=dates,
    )
    frame["high"] = frame[["open", "high", "close"]].max(axis=1)
    frame["low"] = frame[["open", "low", "close"]].min(axis=1)
    return frame


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


def write_walk_forward_fixture(out_dir: Path = FIXTURE_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = build_walk_forward_fixture()
    frame.to_csv(out_dir / "walk_forward_1h.csv", lineterminator="\n", float_format="%.10f")


def write_drift_fixtures(out_dir: Path = FIXTURE_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stable = build_drift_fixture(shifted=False)
    shifted = build_drift_fixture(shifted=True)
    stable.to_csv(out_dir / "drift_stable_1h.csv", lineterminator="\n", float_format="%.10f")
    shifted.to_csv(out_dir / "drift_shifted_1h.csv", lineterminator="\n", float_format="%.10f")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic OHLCV fixtures")
    parser.add_argument("--from-warehouse", dest="warehouse", default=None)
    args = parser.parse_args(argv)
    if args.warehouse:
        df_1h, df_1d = from_warehouse(args.warehouse)
    else:
        df_1h, df_1d = build_fixtures()
    write_fixtures(df_1h, df_1d)
    write_walk_forward_fixture()
    write_drift_fixtures()
    print(f"1h rows={len(df_1h)} last={df_1h.index[-1]}")
    print(f"1d rows={len(df_1d)} last={df_1d.index[-1]}")
    walk_forward = build_walk_forward_fixture()
    print(f"walk_forward rows={len(walk_forward)} last={walk_forward.index[-1]}")
    print(f"drift_stable rows={len(build_drift_fixture(shifted=False))}")
    print(f"drift_shifted rows={len(build_drift_fixture(shifted=True))}")


if __name__ == "__main__":
    main()
