"""Characterization of the pre-phase-3 expired-signal resolution.

The behaviour captured here is the one that gets replaced in phase 3: an
expired signal whose window contains neither the stop nor the target is
valued at the CURRENT market price, so the recorded exit price and exit
time depend on when the reconciliation job happened to run. The phase-3
tests replace this file.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd

from services.trading_service import TradingService


def _frame(rows):
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        [
            {
                "open": 100.0,
                "high": high,
                "low": low,
                "close": close,
            }
            for high, low, close in rows
        ],
        index=[base + timedelta(hours=i) for i in range(len(rows))],
    )


def _service(provider) -> TradingService:
    service = TradingService.__new__(TradingService)
    service.market_data_provider = provider
    return service


def _details(**overrides):
    base = {
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "signal_type": "buy",
    }
    base.update(overrides)
    return base


def test_expired_signal_without_a_hit_is_valued_at_the_current_market_price():
    provider = SimpleNamespace(
        fetch_ohlcv_data=AsyncMock(return_value=_frame([(101.0, 99.0, 100.0)]))
    )
    service = _service(provider)
    created = datetime(2024, 1, 1, tzinfo=UTC)

    outcome = asyncio.run(
        service._decide_expired_outcome(
            symbol="BTC/USDT",
            timeframe="1h",
            details=_details(),
            created_at=created,
            expiry_hours=24.0,
        )
    )

    assert outcome == (False, 100.0)


def test_the_fallback_price_is_taken_from_a_two_candle_reference_fetch():
    provider = SimpleNamespace(
        fetch_ohlcv_data=AsyncMock(return_value=_frame([(101.0, 99.0, 100.0)]))
    )
    service = _service(provider)
    created = datetime(2024, 1, 1, tzinfo=UTC)

    asyncio.run(
        service._decide_expired_outcome(
            symbol="BTC/USDT",
            timeframe="1h",
            details=_details(),
            created_at=created,
            expiry_hours=24.0,
        )
    )

    limits = [call.kwargs.get("limit") for call in provider.fetch_ohlcv_data.await_args_list]
    assert 2 in limits
    assert 500 in limits
