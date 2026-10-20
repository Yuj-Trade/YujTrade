"""Prediction-time feature trace.

Contract: for every emitted signal the exact feature schema and values can be
reconstructed from the runtime store, keyed by signal_id. A trace failure must
never block the signal.
"""

import json
from unittest.mock import MagicMock

import pandas as pd

from strategy.prediction_trace import (
    TRACE_SCHEMA_VERSION,
    PredictionTraceRecorder,
    safe_trace_name,
)

SIGNAL_ID = "BTC/USDT|1h|2025-01-01T00:00:00+00:00|buy"


def _payload() -> dict:
    return {
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "feature_names": ["rsi", "adx"],
        "feature_values": {"rsi": 55.0, "adx": 21.5},
        "ml_predictions": {"xgboost": {"confidence": 71.0}},
        "score": 12.5,
        "threshold_used": 10.0,
    }


class TestSafeNaming:
    def test_path_separators_and_pipes_are_replaced(self):
        name = safe_trace_name(SIGNAL_ID)
        assert "/" not in name
        assert "|" not in name
        assert ":" not in name

    def test_name_is_stable_for_the_same_signal_id(self):
        assert safe_trace_name(SIGNAL_ID) == safe_trace_name(SIGNAL_ID)


class TestRecorder:
    async def test_trace_is_written_keyed_by_signal_id(self, tmp_path):
        recorder = PredictionTraceRecorder(tmp_path / "traces")
        target = await recorder.record(SIGNAL_ID, _payload())
        assert target is not None
        assert target.exists()
        assert target.name == f"{safe_trace_name(SIGNAL_ID)}.json"
        document = json.loads(target.read_text(encoding="utf-8"))
        assert document["schema_version"] == TRACE_SCHEMA_VERSION
        assert document["signal_id"] == SIGNAL_ID
        assert document["feature_values"] == {"rsi": 55.0, "adx": 21.5}

    async def test_disabled_recorder_writes_nothing(self, tmp_path):
        recorder = PredictionTraceRecorder(tmp_path / "traces", enabled=False)
        assert recorder.enabled is False
        assert await recorder.record(SIGNAL_ID, _payload()) is None
        assert not (tmp_path / "traces").exists()

    async def test_unwritable_target_degrades_to_a_warning(self, tmp_path):
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        recorder = PredictionTraceRecorder(blocker)
        assert await recorder.record(SIGNAL_ID, _payload()) is None

    async def test_payload_is_json_serializable_even_with_odd_values(self, tmp_path):
        recorder = PredictionTraceRecorder(tmp_path / "traces")
        payload = _payload()
        payload["feature_values"] = {"rsi": float("nan"), "custom": object()}
        target = await recorder.record(SIGNAL_ID, payload)
        assert target is not None
        document = json.loads(target.read_text(encoding="utf-8"))
        assert document["feature_values"]["rsi"] is None
        assert isinstance(document["feature_values"]["custom"], str)

    def test_path_for_is_predictable(self, tmp_path):
        recorder = PredictionTraceRecorder(tmp_path / "traces")
        assert recorder.path_for(SIGNAL_ID).parent == tmp_path / "traces"


class TestGeneratorIntegration:
    async def test_generator_writes_a_trace_for_an_emitted_signal(self, tmp_path):
        from types import SimpleNamespace

        from strategy.signal_generator import SignalGenerator

        recorder = PredictionTraceRecorder(tmp_path / "traces")
        generator = SignalGenerator(
            data_provider=MagicMock(),
            model_manager=MagicMock(),
            config_manager=MagicMock(),
            trace_recorder=recorder,
        )
        signal = SimpleNamespace(
            timestamp=pd.Timestamp("2025-01-01T00:00:00+00:00"),
            signal_type=SimpleNamespace(value="buy"),
        )
        indicators = {"rsi": {"result": SimpleNamespace(value=55.0)}}
        await generator._record_prediction_trace(
            signal,
            symbol="BTC/USDT",
            timeframe="1h",
            indicators=indicators,
            ml_predictions={"xgboost": {"confidence": 71.0}},
            score=12.5,
            threshold=10.0,
        )
        written = list((tmp_path / "traces").glob("*.json"))
        assert len(written) == 1
        document = json.loads(written[0].read_text(encoding="utf-8"))
        assert document["symbol"] == "BTC/USDT"
        assert document["feature_names"] == ["rsi"]
        assert document["feature_values"] == {"rsi": 55.0}
        assert document["signal_id"].startswith("BTC/USDT|1h|")

    async def test_generator_without_a_recorder_writes_nothing(self, tmp_path):
        from types import SimpleNamespace

        from strategy.signal_generator import SignalGenerator

        generator = SignalGenerator(
            data_provider=MagicMock(),
            model_manager=MagicMock(),
            config_manager=MagicMock(),
        )
        signal = SimpleNamespace(
            timestamp=pd.Timestamp("2025-01-01T00:00:00+00:00"),
            signal_type=SimpleNamespace(value="buy"),
        )
        await generator._record_prediction_trace(
            signal,
            symbol="BTC/USDT",
            timeframe="1h",
            indicators={},
            ml_predictions={},
            score=1.0,
            threshold=10.0,
        )
        assert not list(tmp_path.glob("**/*.json"))
