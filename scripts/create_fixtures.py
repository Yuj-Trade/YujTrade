import asyncio
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

np.random.seed(42)

# Use a fixed end date that's within freshness thresholds (2 hours ago), rounded to hour
FIXED_END_DATE = pd.Timestamp.now(tz='UTC').floor('1h') - timedelta(hours=2)

def create_ohlcv_data(periods, freq, base_price=50000, end_date=None):
    if end_date is None:
        end_date = FIXED_END_DATE
    dates = pd.date_range(
        end=end_date,
        periods=periods,
        freq=freq,
        tz="UTC"
    )
    returns = np.random.normal(0, 0.01, periods)
    prices = base_price * np.exp(np.cumsum(returns))

    df = pd.DataFrame({
        "open": prices * (1 + np.random.uniform(-0.002, 0.002, periods)),
        "high": prices * (1 + np.random.uniform(0, 0.005, periods)),
        "low": prices * (1 - np.random.uniform(0, 0.005, periods)),
        "close": prices,
        "volume": np.random.uniform(100, 10000, periods),
    }, index=dates)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df

# Create 1h data (1500 candles) - recent data
df_1h = create_ohlcv_data(1500, "1h", end_date=FIXED_END_DATE)
df_1h.to_csv("tests/fixtures/ohlcv_1h.csv")
print(f"Created 1h fixture: {len(df_1h)} rows, last date: {df_1h.index[-1]}")

# Create 1d data (1500 candles) - recent data
df_1d = create_ohlcv_data(1500, "1D", end_date=FIXED_END_DATE.floor('1D'))
df_1d.to_csv("tests/fixtures/ohlcv_1d.csv")
print(f"Created 1d fixture: {len(df_1d)} rows, last date: {df_1d.index[-1]}")

print("Fixtures created successfully")
