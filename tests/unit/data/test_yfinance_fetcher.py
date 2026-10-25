import json
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd

from data.sources.yfinance_fetcher import YFinanceFetcher


def _fetcher(redis_client=None):
    fetcher = YFinanceFetcher(redis_client=redis_client)
    fetcher.config_manager.get_cache_ttl = lambda *args, **kwargs: 600
    return fetcher


def _download_frame(columns: str | None = None):
    index = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    tickers = ["DX-Y.NYB", "^GSPC", "^IXIC", "^VIX", "GC=F", "CL=F", "^DJI", "^RUT"]
    data = {}
    for ticker in tickers:
        values = np.arange(5, dtype=float) + 100 if columns != "flat" else np.full(5, 100.0)
        data[("Close", ticker)] = values
    frame = pd.DataFrame(data, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Price", "Ticker"])
    return frame


async def test_indices_are_parsed_from_the_download(monkeypatch):
    fetcher = _fetcher()
    monkeypatch.setattr(
        "data.sources.yfinance_fetcher.yf.download", lambda **kwargs: _download_frame()
    )

    result = await fetcher.get_traditional_indices()

    assert set(result) == {"DXY", "SPX", "NDX", "VIX", "GOLD", "OIL", "DJI", "RUT"}
    assert result["DXY"] == 104.0


async def test_empty_download_returns_empty_dict(monkeypatch):
    fetcher = _fetcher()
    monkeypatch.setattr(
        "data.sources.yfinance_fetcher.yf.download", lambda **kwargs: pd.DataFrame()
    )

    assert await fetcher.get_traditional_indices() == {}


async def test_missing_close_column_returns_empty_dict(monkeypatch):
    fetcher = _fetcher()
    monkeypatch.setattr(
        "data.sources.yfinance_fetcher.yf.download",
        lambda **kwargs: pd.DataFrame({"Open": [1.0]}),
    )

    assert await fetcher.get_traditional_indices() == {}


async def test_missing_tickers_are_skipped(monkeypatch):
    fetcher = _fetcher()
    index = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    frame = pd.DataFrame({("Close", "^GSPC"): [100.0, 101.0]}, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Price", "Ticker"])
    monkeypatch.setattr("data.sources.yfinance_fetcher.yf.download", lambda **kwargs: frame)

    result = await fetcher.get_traditional_indices()

    assert result == {"SPX": 101.0}


async def test_nan_prices_are_skipped(monkeypatch):
    fetcher = _fetcher()
    index = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    frame = pd.DataFrame(
        {("Close", "^GSPC"): [np.nan, np.nan], ("Close", "^VIX"): [10.0, 11.0]}, index=index
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Price", "Ticker"])
    monkeypatch.setattr("data.sources.yfinance_fetcher.yf.download", lambda **kwargs: frame)

    assert await fetcher.get_traditional_indices() == {"VIX": 11.0}


async def test_result_is_cached(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    fetcher = _fetcher(redis_client=redis)
    monkeypatch.setattr(
        "data.sources.yfinance_fetcher.yf.download", lambda **kwargs: _download_frame()
    )

    await fetcher.get_traditional_indices()

    redis.set.assert_awaited_once()
    assert json.loads(redis.set.await_args.args[1])["SPX"] == 104.0


async def test_cache_hit_skips_the_download(monkeypatch):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps({"SPX": 1.0}))
    fetcher = _fetcher(redis_client=redis)
    download = AsyncMock()
    monkeypatch.setattr("data.sources.yfinance_fetcher.yf.download", download)

    assert await fetcher.get_traditional_indices() == {"SPX": 1.0}
    download.assert_not_called()
