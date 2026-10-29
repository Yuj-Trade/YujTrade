"""Pin the service quality gates and expired-outcome resolution.

These tests lock current behavior BEFORE the domain-delegation refactor
(phase H): `_passes_quality_gates` and `_decide_expired_outcome` must keep
returning identical results after they delegate to `domain`.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd

from common.core import SignalType, TradingSignal
from services.trading_service import TradingService


def _service(provider=None) -> TradingService:
    service = TradingService.__new__(TradingService)
    service.market_data_provider = provider
    return service


def _signal(**overrides) -> TradingSignal:
    base = {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 100.0,
        "exit_price": 110.0,
        "stop_loss": 95.0,
        "timestamp": datetime.now(UTC),
        "timeframe": "1h",
        "confidence_score": 90.0,
        "reasons": ["trend up"],
        "risk_reward_ratio": 3.0,
        "predicted_profit": 10.0,
        "volume_analysis": {"volume_ratio": 2.0},
        "market_context": {"trend_strength": "STRONG"},
        "dynamic_levels": {},
    }
    base.update(overrides)
    return TradingSignal(**base)


class TestPassesQualityGates:
    def test_clean_signal_passes(self):
        assert _service()._passes_quality_gates(_signal()) is True

    def test_low_confidence_fails(self):
        assert _service()._passes_quality_gates(_signal(confidence_score=70.0)) is False

    def test_weak_trend_fails(self):
        signal = _signal(market_context={"trend_strength": "WEAK"})
        assert _service()._passes_quality_gates(signal) is False

    def test_low_surge_fails(self):
        signal = _signal(volume_analysis={"volume_ratio": 1.0})
        assert _service()._passes_quality_gates(signal) is False

    def test_missing_ratio_skips_surge_gate(self):
        signal = _signal(volume_analysis={})
        assert _service()._passes_quality_gates(signal) is True

    def test_unknown_timeframe_has_no_confidence_gate(self):
        assert _service()._passes_quality_gates(_signal(timeframe="9h")) is True


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
    def _run(self, provider, **kwargs):
        service = _service(provider)
        created = datetime(2024, 1, 1, tzinfo=UTC)
        params = {
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "details": _details(),
            "created_at": created,
            "expiry_hours": 3.0,
            "now": created + timedelta(hours=4),
        }
        params.update(kwargs)
        return asyncio.run(service._resolve_signal_outcome(**params))

    def test_stop_hit_resolves_failure(self):
        provider = SimpleNamespace(
            fetch_ohlcv_range=AsyncMock(
                return_value=_frame(
                    [(112.0, 94.0, 100.0), (101.0, 99.0, 100.0), (101.0, 99.0, 100.0)]
                )
            )
        )
        resolution = self._run(provider)
        assert resolution is not None
        assert resolution.exit_reason == "stop"
        assert resolution.exit_price == 95.0

    def test_target_hit_resolves_success(self):
        provider = SimpleNamespace(
            fetch_ohlcv_range=AsyncMock(
                return_value=_frame(
                    [(101.0, 99.0, 100.0), (112.0, 101.0, 110.0), (101.0, 99.0, 100.0)]
                )
            )
        )
        resolution = self._run(provider)
        assert resolution is not None
        assert resolution.exit_reason == "target"
        assert resolution.exit_price == 110.0

    def test_no_hit_expires_at_the_last_close_of_the_window(self):
        provider = SimpleNamespace(
            fetch_ohlcv_range=AsyncMock(
                return_value=_frame(
                    [(101.0, 99.0, 100.0), (101.0, 99.0, 101.0), (101.0, 99.0, 102.0)]
                )
            )
        )
        resolution = self._run(provider)
        assert resolution is not None
        assert resolution.exit_reason == "expired"
        assert resolution.exit_price == 102.0

    def test_no_data_before_the_window_end_stays_pending(self):
        provider = SimpleNamespace(fetch_ohlcv_range=AsyncMock(return_value=pd.DataFrame()))
        created = datetime(2024, 1, 1, tzinfo=UTC)
        assert self._run(provider, created_at=created, now=created + timedelta(hours=1)) is None

    def test_no_data_after_the_window_end_resolves_to_no_data(self):
        provider = SimpleNamespace(fetch_ohlcv_range=AsyncMock(return_value=pd.DataFrame()))
        created = datetime(2024, 1, 1, tzinfo=UTC)
        resolution = self._run(provider, created_at=created, now=created + timedelta(hours=4))
        assert resolution is not None
        assert resolution.exit_reason == "no_data"

    def test_malformed_rows_skipped(self):
        frame = _frame([(112.0, 101.0, 110.0), (101.0, 99.0, 100.0), (101.0, 99.0, 100.0)])
        frame.loc[frame.index[0], "high"] = None
        provider = SimpleNamespace(fetch_ohlcv_range=AsyncMock(return_value=frame))
        resolution = self._run(provider)
        assert resolution is not None
        assert resolution.exit_reason == "expired"
        assert resolution.exit_price == 100.0


class TestBuildPerformanceReport:
    def _service(self, tmp_path, ledger):
        from config.settings import ConfigManager

        service = TradingService.__new__(TradingService)
        service.performance_ledger = ledger
        service.config_manager = ConfigManager(
            config_path=str(tmp_path / "config.json"),
            weights_path=str(tmp_path / "weights.json"),
        )
        return service

    async def test_the_service_loads_the_ledger_and_delegates(self, tmp_path):
        from domain.performance import ResolutionRecord
        from trading.ledger import PaperLedger

        ledger = PaperLedger(tmp_path / "paper_ledger.db")
        await ledger.record_resolution(
            ResolutionRecord(
                signal_id="sig-1",
                symbol="BTC/USDT",
                timeframe="1h",
                side="buy",
                entry=100.0,
                stop=90.0,
                target=120.0,
                created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
                exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
                exit_price=120.0,
                exit_reason="target",
                candles_used=4,
                resolver_version="paper-resolution-v1",
            )
        )
        service = self._service(tmp_path, ledger)

        report = await service.build_performance_report(datetime(2026, 10, 20, tzinfo=UTC))

        assert report.mode == "paper"
        assert report.total_resolved == 1
        assert report.status == "insufficient_sample"
        assert report.exit_counts["target"] == 1

    async def test_a_service_without_a_ledger_reports_no_trades(self, tmp_path):
        service = self._service(tmp_path, None)

        report = await service.build_performance_report(datetime(2026, 10, 20, tzinfo=UTC))

        assert report.status == "no_trades"
        assert report.total_resolved == 0
