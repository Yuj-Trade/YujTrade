from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import services.trading_service as trading_service_module
from common.core import SignalType, TradingSignal
from config.logger import logger as root_logger
from domain.outcome import Resolution
from services.trading_service import TradingService


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


def _service(signal=None, multi_tf=None) -> TradingService:
    service = TradingService.__new__(TradingService)
    service.invalid_symbols = set()
    service._cycle_log = root_logger.bind(run_id="test-run-id")

    provider = SimpleNamespace(fetch_ohlcv_data=AsyncMock(return_value=MagicMock(empty=False)))
    service.market_data_provider = provider

    generated = MagicMock()
    generated.generate_signal = AsyncMock(return_value=signal)
    service.signal_generator = generated

    confirmation = MagicMock()
    confirmation.get_confirmation_score = AsyncMock(return_value=multi_tf or (0.9, None, False))
    service.multi_tf_analyzer = confirmation

    service.signal_tracker = MagicMock()
    service.signal_tracker.record = AsyncMock()
    return service


class TestCycleCorrelationIds:
    async def test_analyze_symbol_logs_carry_run_id(self):
        service = _service(signal=_signal())

        captured = []

        def sink(message):
            captured.append(str(message))

        handler_id = root_logger.add(sink, format="{message}|{extra}")
        try:
            await service.analyze_symbol("BTC/USDT", "1h")
        finally:
            root_logger.remove(handler_id)

        assert any("test-run-id" in line for line in captured)

    async def test_emitted_signal_logs_carry_signal_id(self):
        signal = _signal()
        service = _service(signal=signal)

        captured = []

        def sink(message):
            captured.append(str(message))

        handler_id = root_logger.add(sink, format="{message}|{extra}")
        try:
            await service.analyze_symbol("BTC/USDT", "1h")
        finally:
            root_logger.remove(handler_id)

        assert any("signal_id" in line for line in captured)


class TestMetricsWiring:
    async def test_candidate_and_emitted_signal_metrics(self, monkeypatch):
        candidate_mock = MagicMock()
        gate_mock = MagicMock()
        signal_mock = MagicMock()
        monkeypatch.setattr(trading_service_module.metrics, "record_candidate", candidate_mock)
        monkeypatch.setattr(trading_service_module.metrics, "record_gate_rejection", gate_mock)
        monkeypatch.setattr(trading_service_module.metrics, "record_signal", signal_mock)

        signal = _signal()
        service = _service(signal=signal)
        await service.analyze_symbol("BTC/USDT", "1h")

        candidate_mock.assert_called_once_with("BTC/USDT", "1h")
        gate_mock.assert_not_called()

    async def test_multi_timeframe_rejection_records_gate_metric(self, monkeypatch):
        candidate_mock = MagicMock()
        gate_mock = MagicMock()
        monkeypatch.setattr(trading_service_module.metrics, "record_candidate", candidate_mock)
        monkeypatch.setattr(trading_service_module.metrics, "record_gate_rejection", gate_mock)

        service = _service(signal=_signal(), multi_tf=(0.1, None, False))
        result = await service.analyze_symbol("BTC/USDT", "1h")

        assert result is None
        candidate_mock.assert_called_once()
        gate_mock.assert_called_once_with("multi_timeframe")

    async def test_quality_gate_rejection_records_gate_metric(self, monkeypatch):
        gate_mock = MagicMock()
        monkeypatch.setattr(trading_service_module.metrics, "record_gate_rejection", gate_mock)

        weak = _signal(confidence_score=10.0, market_context={"trend_strength": "WEAK"})
        service = _service(signal=weak)
        result = await service.analyze_symbol("BTC/USDT", "1h")

        assert result is None
        gate_mock.assert_called_once_with("quality_gates")

    async def test_reconcile_resolution_records_outcome_metric(self, monkeypatch):
        resolution_mock = MagicMock()
        monkeypatch.setattr(trading_service_module.metrics, "record_resolution", resolution_mock)

        service = TradingService.__new__(TradingService)
        service._cycle_log = root_logger.bind(run_id="reconcile-run")
        expired_details = {
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "entry": 100.0,
            "stop": 95.0,
            "target": 110.0,
            "signal_type": "buy",
            "created_at": datetime.now(UTC).isoformat(),
            "confidence": 90.0,
            "threshold_used": 12.0,
            "threshold_regime": "high|mid",
        }
        service.signal_tracker = SimpleNamespace(
            get_pending_expired=AsyncMock(
                return_value=[{"signal_id": "BTC/USDT|1h|t|buy", "details": expired_details}]
            ),
            resolve=AsyncMock(),
            update_resolution_details=AsyncMock(),
        )
        service.market_data_provider = SimpleNamespace(
            fetch_ohlcv_data=AsyncMock(return_value=None)
        )
        service.model_manager = SimpleNamespace(record_signal_performance=AsyncMock())
        threshold_manager = MagicMock()
        threshold_manager.flush = AsyncMock()
        service.signal_generator = SimpleNamespace(threshold_manager=threshold_manager)

        async def fake_resolve(symbol, timeframe, details, created_at, expiry_hours):
            return Resolution("target", 110.0, datetime.now(UTC), 3)

        service._resolve_signal_outcome = fake_resolve

        resolved = await service.reconcile_pending_signals()

        assert resolved == 1
        resolution_mock.assert_called_once_with(True)
        threshold_manager.record_performance.assert_called_once()
