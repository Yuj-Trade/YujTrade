"""Resolution behaviour of the reconciliation path.

These tests replace the phase-1 characterization: the current-price
fallback is gone, an expired signal is valued at the close of the last
candle inside its window and an uncovered window resolves to `no_data`.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from domain.outcome import Resolution
from services.trading_service import TradingService


def _frame(rows, start=datetime(2024, 1, 1, tzinfo=UTC)):
    return pd.DataFrame(
        [{"open": 100.0, "high": high, "low": low, "close": close} for high, low, close in rows],
        index=[start + timedelta(hours=i) for i in range(len(rows))],
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


class TestResolveSignalOutcome:
    def _run(self, rows, **kwargs):
        provider = SimpleNamespace(fetch_ohlcv_data=AsyncMock(return_value=_frame(rows)))
        service = _service(provider)
        created = datetime(2024, 1, 1, tzinfo=UTC)
        params = {
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "details": _details(),
            "created_at": created,
            "expiry_hours": 3.0,
        }
        params.update(kwargs)
        return asyncio.run(service._resolve_signal_outcome(**params))

    def test_a_stop_hit_resolves_to_the_stop_price(self):
        resolution = self._run([(101.0, 94.0, 100.0), (101.0, 99.0, 100.0), (101.0, 99.0, 100.0)])

        assert resolution is not None
        assert resolution.exit_reason == "stop"
        assert resolution.exit_price == 95.0

    def test_a_target_hit_resolves_to_the_target_price(self):
        resolution = self._run([(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)])

        assert resolution is not None
        assert resolution.exit_reason == "target"
        assert resolution.exit_price == 110.0

    def test_an_expired_signal_uses_the_last_close_inside_the_window(self):
        resolution = self._run([(101.0, 99.0, 100.0), (101.0, 99.0, 101.5), (101.0, 99.0, 102.5)])

        assert resolution is not None
        assert resolution.exit_reason == "expired"
        assert resolution.exit_price == 102.5
        assert resolution.exit_at == datetime(2024, 1, 1, 2, tzinfo=UTC)

    def test_the_current_price_is_never_used_as_an_exit_price(self):
        provider = SimpleNamespace(
            fetch_ohlcv_data=AsyncMock(
                return_value=_frame(
                    [(101.0, 99.0, 100.0), (101.0, 99.0, 101.5), (101.0, 99.0, 102.5)]
                )
            )
        )
        service = _service(provider)
        created = datetime(2024, 1, 1, tzinfo=UTC)

        resolution = asyncio.run(
            service._resolve_signal_outcome(
                symbol="BTC/USDT",
                timeframe="1h",
                details=_details(),
                created_at=created,
                expiry_hours=3.0,
            )
        )

        assert resolution is not None
        assert resolution.exit_price == 102.5
        assert not any(
            call.kwargs.get("limit") == 2 for call in provider.fetch_ohlcv_data.await_args_list
        )

    def test_the_candle_count_is_derived_from_the_expiry_and_the_candle_duration(self):
        provider = SimpleNamespace(
            fetch_ohlcv_data=AsyncMock(
                return_value=_frame(
                    [(101.0, 99.0, 100.0), (101.0, 99.0, 101.5), (101.0, 99.0, 102.5)]
                )
            )
        )
        service = _service(provider)
        created = datetime(2024, 1, 1, tzinfo=UTC)

        asyncio.run(
            service._resolve_signal_outcome(
                symbol="BTC/USDT",
                timeframe="1h",
                details=_details(),
                created_at=created,
                expiry_hours=3.0,
            )
        )

        limits = [call.kwargs.get("limit") for call in provider.fetch_ohlcv_data.await_args_list]
        assert limits == [5]

    def test_an_incomplete_window_resolves_to_no_data(self):
        provider = SimpleNamespace(
            fetch_ohlcv_data=AsyncMock(
                return_value=_frame([(101.0, 99.0, 100.0), (101.0, 99.0, 101.5)])
            )
        )
        service = _service(provider)
        created = datetime(2024, 1, 1, tzinfo=UTC)

        resolution = asyncio.run(
            service._resolve_signal_outcome(
                symbol="BTC/USDT",
                timeframe="1h",
                details=_details(),
                created_at=created,
                expiry_hours=12.0,
            )
        )

        assert resolution is not None
        assert resolution.exit_reason == "no_data"
        assert resolution.exit_price is None
        assert resolution.exit_at is None

    def test_an_unknown_timeframe_raises_an_explicit_error(self):
        provider = SimpleNamespace(
            fetch_ohlcv_data=AsyncMock(return_value=_frame([(101.0, 99.0, 100.0)]))
        )
        service = _service(provider)
        created = datetime(2024, 1, 1, tzinfo=UTC)

        with pytest.raises(ValueError):
            asyncio.run(
                service._resolve_signal_outcome(
                    symbol="BTC/USDT",
                    timeframe="9h",
                    details=_details(),
                    created_at=created,
                    expiry_hours=3.0,
                )
            )

    def test_missing_levels_skip_the_signal(self):
        provider = SimpleNamespace(
            fetch_ohlcv_data=AsyncMock(return_value=_frame([(101.0, 99.0, 100.0)]))
        )
        service = _service(provider)
        created = datetime(2024, 1, 1, tzinfo=UTC)

        resolution = asyncio.run(
            service._resolve_signal_outcome(
                symbol="BTC/USDT",
                timeframe="1h",
                details={"entry": 100.0, "signal_type": "buy"},
                created_at=created,
                expiry_hours=3.0,
            )
        )

        assert resolution is None


class TestTrackerOutcome:
    def test_a_target_is_a_win(self):
        details = _details()

        assert (
            TradingService._tracker_outcome(details, Resolution("target", 110.0, None, 1)) is True
        )

    def test_a_stop_is_a_loss(self):
        details = _details()

        assert TradingService._tracker_outcome(details, Resolution("stop", 95.0, None, 1)) is False

    def test_an_expired_buy_above_the_entry_is_a_win(self):
        details = _details()

        assert (
            TradingService._tracker_outcome(details, Resolution("expired", 101.0, None, 1)) is True
        )

    def test_an_expired_buy_below_the_entry_is_a_loss(self):
        details = _details()

        assert (
            TradingService._tracker_outcome(details, Resolution("expired", 99.0, None, 1)) is False
        )

    def test_an_expired_sell_below_the_entry_is_a_win(self):
        details = _details(signal_type="sell", stop=105.0)

        assert (
            TradingService._tracker_outcome(details, Resolution("expired", 99.0, None, 1)) is True
        )
