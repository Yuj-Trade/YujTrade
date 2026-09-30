import sys
sys.path.insert(0, ".")
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time

np.random.seed(42)
dates = pd.date_range(end=datetime.now(timezone.utc), periods=600, freq="1h", tz="UTC")
prices = 50000 * np.exp(np.cumsum(np.random.normal(0, 0.01, 600)))
df = pd.DataFrame(
    {
        "open": prices,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": np.random.uniform(100, 10000, 600),
    },
    index=dates,
)

from common.utils import detect_market_regime

t0 = time.time()
regime = detect_market_regime(df)
print("regime OK in %.2fs:" % (time.time() - t0), regime)
regime150 = detect_market_regime(df, lookback=150)
print("regime(150):", {k: regime150[k] for k in ("market_type", "volatility_regime", "trend_persistence", "hurst_exponent")})

from data.data_provider import MarketDataProvider

class DummyChk:
    pass

from unittest.mock import MagicMock
p = MarketDataProvider(MagicMock(), MagicMock())
print("quality score (expect 100.0):", p._get_data_quality_score(df, "1h"))

# trending fixture for regime keys
up = pd.DataFrame(
    {
        "open": np.linspace(100, 200, 300),
        "high": np.linspace(101, 201, 300),
        "low": np.linspace(99, 199, 300),
        "close": np.linspace(100, 200, 300),
        "volume": np.linspace(1000, 5000, 300),
    },
    index=pd.date_range(end=datetime.now(timezone.utc), periods=300, freq="1h", tz="UTC"),
)
r2 = detect_market_regime(up, lookback=150)
print("trending regime:", {k: r2[k] for k in ("market_type", "adx", "volatility_regime", "trend_persistence", "hurst_exponent")})
print("all keys:", sorted(r2.keys()))
