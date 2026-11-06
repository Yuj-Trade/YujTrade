import inspect
import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from common.exceptions import PortfolioRiskUnavailable
from config.logger import logger
from domain.portfolio_risk import PortfolioRiskView


def _close_by_timestamp(frame: Any) -> dict[Any, float]:
    closes: dict[Any, float] = {}
    if frame is None:
        return closes
    if isinstance(frame, dict):
        return _close_by_timestamp_dict(frame)
    if not isinstance(frame, pd.DataFrame):
        return closes
    if frame.empty or "close" not in frame.columns:
        return closes
    if "timestamp" in frame.columns:
        index = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    else:
        index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    values = pd.to_numeric(frame["close"], errors="coerce")
    for moment, value in zip(index, values):
        if moment is None or pd.isna(moment):
            continue
        if value is None or pd.isna(value):
            continue
        closes[pd.Timestamp(moment)] = float(value)
    return closes


def _close_by_timestamp_dict(frame: dict[str, Any]) -> dict[Any, float]:
    closes: dict[Any, float] = {}
    timestamps = frame.get("timestamp") or frame.get("timestamps") or []
    values = frame.get("close") or frame.get("closes") or []
    for moment, value in zip(timestamps, values):
        if moment is None:
            continue
        try:
            moment = pd.Timestamp(moment)
        except (TypeError, ValueError):
            continue
        if pd.isna(moment):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        closes[moment] = number
    return closes


async def _fetch_closes(
    provider: Any, symbols: list[str], limit: int
) -> dict[str, dict[Any, float]]:
    fetched: dict[str, dict[Any, float]] = {}
    for symbol in symbols:
        try:
            frame = provider.fetch_ohlcv_data(symbol, "1d", limit=limit)
            if inspect.isawaitable(frame):
                frame = await frame
        except Exception as exc:
            logger.warning(f"Portfolio risk view fetch failed for {symbol}: {exc}")
            continue
        closes = _close_by_timestamp(frame)
        if closes:
            fetched[symbol] = closes
    return fetched


def _common_timestamps(fetched: dict[str, dict[Any, float]]) -> list[Any]:
    common: set[Any] | None = None
    for closes in fetched.values():
        moments = set(closes)
        common = moments if common is None else (common & moments)
    if not common:
        return []
    return sorted(common)


async def build_portfolio_risk_view(
    provider: Any,
    symbols: list[str],
    lookback_days: int,
    min_overlap: int,
) -> PortfolioRiskView:
    limit = int(lookback_days) + 1
    fetched = await _fetch_closes(provider, list(symbols), limit)
    if len(fetched) < 2:
        logger.warning(
            f"portfolio_view_unavailable: only {len(fetched)} symbol(s) returned candles"
        )
        raise PortfolioRiskUnavailable("fewer than two symbols returned candles")

    common = _common_timestamps(fetched)
    if len(common) < 2:
        logger.warning("portfolio_view_unavailable: no common candles across symbols")
        raise PortfolioRiskUnavailable("no common candles across symbols")

    kept: list[str] = []
    dropped: list[str] = []
    for symbol in sorted(fetched):
        available = sum(1 for moment in common if moment in fetched[symbol])
        if available >= int(min_overlap):
            kept.append(symbol)
        else:
            dropped.append(symbol)
    if dropped:
        logger.warning(
            f"portfolio_view_symbols_dropped: {dropped} below min overlap {min_overlap}"
        )
    if len(kept) < 2:
        logger.warning(
            f"portfolio_view_unavailable: only {len(kept)} symbol(s) meet min overlap"
        )
        raise PortfolioRiskUnavailable("fewer than two symbols meet the minimum overlap")

    close_rows: list[list[float]] = []
    for symbol in kept:
        close_rows.append([fetched[symbol][moment] for moment in common])

    returns: list[tuple[float, ...]] = []
    for row in close_rows:
        series: list[float] = []
        for position in range(1, len(row)):
            previous = row[position - 1]
            current = row[position]
            if previous <= 0.0 or current <= 0.0:
                raise PortfolioRiskUnavailable("non-positive close in aligned series")
            series.append(math.log(current / previous))
        returns.append(tuple(series))

    matrix = np.array(returns, dtype=float).T
    if matrix.shape[0] < 2 or matrix.shape[1] < 2:
        logger.warning("portfolio_view_unavailable: insufficient return rows")
        raise PortfolioRiskUnavailable("insufficient return rows")
    if not np.all(np.isfinite(matrix)):
        logger.warning("portfolio_view_unavailable: non-finite returns")
        raise PortfolioRiskUnavailable("non-finite returns")

    covariance = LedoitWolf().fit(matrix).covariance_
    if not np.all(np.isfinite(covariance)):
        logger.warning("portfolio_view_unavailable: non-finite covariance")
        raise PortfolioRiskUnavailable("non-finite covariance")

    last_close = tuple(float(row[-1]) for row in close_rows)
    return PortfolioRiskView(
        symbols=tuple(kept),
        last_close=last_close,
        returns=tuple(returns),
        covariance=tuple(tuple(float(value) for value in row) for row in covariance),
    )
