"""Prediction-time capture, store parity and the learner fallback (P7)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from features.feature_store import FeatureStore
from modeling.learner import LearningSettings, ModelLearner

_BASE = datetime(2026, 10, 1, tzinfo=UTC)


class _FakeStore:
    def __init__(self, rows=0, frame=None):
        self.recorded = []
        self.rows = rows
        self.frame = frame
        self.count_labeled = AsyncMock(side_effect=lambda *args: self.rows)
        self.training_frame = AsyncMock(return_value=frame)

    async def record_vector(self, symbol, timeframe, moment, feature_list, values):
        self.recorded.append((symbol, timeframe, moment, feature_list, values))
        return True


class _Config:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


def _generator(store):
    from strategy.signal_generator import SignalGenerator

    config = _Config({"indicator_history_path": "runs/indicator_history.db"})
    manager = SimpleNamespace(
        predict_with_confidence=AsyncMock(
            side_effect=[
                {
                    "prediction": 1.0,
                    "confidence": 10.0,
                    "feature_vector": {"close": 100.0, "rsi": 55.0},
                    "candle_time": pd.Timestamp(_BASE),
                },
                None,
            ]
        )
    )
    provider = SimpleNamespace()
    return SignalGenerator(provider, manager, config, feature_store=store)


def test_the_ml_vector_is_recorded_once_per_candle():
    store = _FakeStore()
    generator = _generator(store)

    import asyncio

    predictions = asyncio.run(generator.get_ml_predictions("BTC/USDT", "1h"))

    assert set(predictions) == {"lstm"}
    assert len(store.recorded) == 1
    symbol, timeframe, moment, feature_list, values = store.recorded[0]
    assert symbol == "BTC/USDT"
    assert timeframe == "1h"
    assert moment == _BASE
    assert feature_list == ["close", "rsi"]
    assert values == {"close": 100.0, "rsi": 55.0}


def test_a_store_failure_never_changes_the_signal_inputs():
    store = _FakeStore()
    store.record_vector = AsyncMock(side_effect=RuntimeError("disk full"))
    generator = _generator(store)

    import asyncio

    predictions = asyncio.run(generator.get_ml_predictions("BTC/USDT", "1h"))

    assert set(predictions) == {"lstm"}
    assert predictions["lstm"]["prediction"] == 1.0


def test_no_vector_means_nothing_is_recorded():
    store = _FakeStore()
    generator = _generator(store)
    generator.model_manager.predict_with_confidence = AsyncMock(return_value=None)

    import asyncio

    asyncio.run(generator.get_ml_predictions("BTC/USDT", "1h"))

    assert store.recorded == []


def _learner(tmp_path, rows, feature_frame=None, training_source="feature_store"):
    config = _Config(
        {
            "model_learning": {
                "enabled": True,
                "training_source": training_source,
                "min_new_candles": 0,
            },
            "feature_store_min_rows": 10,
        }
    )
    manager = MagicMock()
    manager.artifacts.read_metadata = MagicMock(return_value={"feature_list": ["close", "volume"]})
    manager.train_model = AsyncMock(
        return_value=SimpleNamespace(version="v1", oos_metrics={}, promoted=False, artifact_path="")
    )
    store = _FakeStore(rows=rows, frame=feature_frame)
    provider = SimpleNamespace(
        get_data_for_model=AsyncMock(return_value=pd.DataFrame({"close": [1.0] * 60}))
    )
    learner = ModelLearner(manager, provider, config)
    learner.feature_store = store
    return learner


def _run(learner):
    import asyncio

    asyncio.run(learner._run_job("xgboost-BTC/USDT-1h", "xgboost", "BTC/USDT", "1h"))


def test_a_low_row_count_falls_back_to_ohlcv():
    learner = _learner(None, rows=3)

    _run(learner)

    args = learner.model_manager.train_model.await_args
    assert args.kwargs["feature_frame"] is None
    learner.feature_store.training_frame.assert_not_called()


def test_a_missing_feature_list_falls_back():
    learner = _learner(None, rows=100)
    learner.model_manager.artifacts.read_metadata = MagicMock(return_value=None)

    _run(learner)

    assert learner.model_manager.train_model.await_args.kwargs["feature_frame"] is None


def test_a_store_frame_is_passed_when_enough_rows_exist():
    frame = pd.DataFrame({"close": [1.0] * 20, "volume": [2.0] * 20, "label_close": [3.0] * 20})
    learner = _learner(None, rows=100, feature_frame=frame)

    _run(learner)

    passed = learner.model_manager.train_model.await_args.kwargs["feature_frame"]
    assert passed is frame


def test_the_ohlcv_source_never_touches_the_store():
    learner = _learner(None, rows=100, training_source="ohlcv")

    _run(learner)

    learner.feature_store.count_labeled.assert_not_called()
    assert learner.model_manager.train_model.await_args.kwargs["feature_frame"] is None


def test_the_default_training_source_is_ohlcv():
    settings = LearningSettings.from_config(_Config({}))
    assert settings.training_source == "ohlcv"
    assert settings.alert_drift_cooldown_hours == 24.0


def test_a_real_store_round_trips_into_a_training_frame(tmp_path):
    store = FeatureStore(tmp_path / "feature_store.db")
    old = (datetime.now(UTC) - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)

    import asyncio

    asyncio.run(store.record_vector("BTC/USDT", "1h", old, ["close"], {"close": 100.0}))
    index = pd.DatetimeIndex([old + timedelta(hours=1), old + timedelta(hours=2)])
    candles = pd.DataFrame({"close": [101.0, 102.0]}, index=index)
    asyncio.run(store.label_pending("BTC/USDT", "1h", candles))

    frame = asyncio.run(
        store.training_frame("BTC/USDT", "1h", ["close"], label_before=datetime.now(UTC))
    )

    assert frame["label_close"].iloc[0] == pytest.approx(101.0)
    assert frame.index[0] == old


def test_the_feature_engineer_matches_the_stored_vector(tmp_path):
    from features.feature_engineering import FeatureEngineer

    index = pd.DatetimeIndex([_BASE + timedelta(hours=index) for index in range(60)])
    frame = pd.DataFrame(
        {
            "open": [100.0 + index for index in range(60)],
            "high": [101.0 + index for index in range(60)],
            "low": [99.0 + index for index in range(60)],
            "close": [100.5 + index for index in range(60)],
            "volume": [10.0 + index for index in range(60)],
        },
        index=index,
    )
    engineer = FeatureEngineer()
    features = engineer.create_features(frame, indicators_to_run=["rsi"])
    feature_list = sorted(features.columns)
    last = features.tail(1).iloc[0]
    vector = {name: float(last[name]) for name in feature_list}

    store = FeatureStore(tmp_path / "feature_store.db")
    import asyncio

    asyncio.run(store.record_vector("BTC/USDT", "1h", _BASE, feature_list, vector))
    recorded = asyncio.run(_fetch_values(store, "BTC/USDT", "1h", _BASE, feature_list))

    for name in feature_list:
        assert recorded[name] == pytest.approx(vector[name], abs=1e-9)


async def _fetch_values(store, symbol, timeframe, candle_time, feature_list):
    import json

    import aiosqlite

    async with aiosqlite.connect(store.path) as connection:
        cursor = await connection.execute(
            "SELECT values_json FROM feature_vectors WHERE symbol = ? AND timeframe = ?",
            (symbol, timeframe),
        )
        row = await cursor.fetchone()
    return json.loads(row[0])
