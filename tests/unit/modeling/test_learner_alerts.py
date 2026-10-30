"""The learner emits alerts and drift notices without breaking learning (P8)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd

from application.learning_alerts import LearningEvent
from modeling.learner import ModelLearner


class _Sink:
    def __init__(self, fail=False):
        self.events: list[LearningEvent] = []
        self.fail = fail

    async def send(self, event):
        if self.fail:
            raise RuntimeError("sink down")
        self.events.append(event)


class _Config:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


_FIXTURES = "tests/fixtures"


def _frame(drifted=False) -> pd.DataFrame:
    name = "drift_shifted_1h.csv" if drifted else "drift_stable_1h.csv"
    return pd.read_csv(f"{_FIXTURES}/{name}", index_col=0, parse_dates=True)


def _clock_seq(values):
    iterator = iter(values)
    return lambda: next(iterator)


def _learner(outcome, *, data=None, sink=None, clock=None, settings=None):
    config = _Config({"model_learning": settings or {"enabled": True, "min_new_candles": 0}})
    manager = MagicMock()
    manager.artifacts.read_metadata = MagicMock(return_value={"oos_metrics": {}})
    manager.train_model = AsyncMock(return_value=outcome)
    manager.artifacts.promote_version = MagicMock()
    provider = SimpleNamespace(
        get_data_for_model=AsyncMock(return_value=data if data is not None else _frame())
    )
    learner = ModelLearner(manager, provider, config, clock=clock or (lambda: 0.0))
    learner.alert_sink = sink
    return learner


async def _run(learner, key="xgboost-BTC/USDT-1h", model_type="xgboost"):
    await learner._run_job(key, model_type, "BTC/USDT", "1h")


def _outcome(version="v2"):
    return SimpleNamespace(version=version, oos_metrics={}, promoted=True, artifact_path="")


def test_a_promotion_is_announced():
    sink = _Sink()
    learner = _learner(_outcome(), sink=sink)

    asyncio.run(_run(learner))

    kinds = [event.kind for event in sink.events]
    assert "promoted" in kinds


def test_a_rejection_is_announced_with_the_reasons():
    from modeling.promotion import PromotionPolicy

    policy = PromotionPolicy(
        max_directional_accuracy_drop=0.0,
        max_rmse_increase_ratio=1.0,
    )
    sink = _Sink()
    learner = _learner(
        SimpleNamespace(
            version="v3",
            oos_metrics={"directional_accuracy": 0.1, "rmse": 1000.0},
            promoted=False,
            artifact_path="",
        ),
        sink=sink,
    )
    learner.policy = policy
    learner.model_manager.artifacts.read_metadata = MagicMock(
        return_value={"oos_metrics": {"directional_accuracy": 0.9, "rmse": 1.0}}
    )

    asyncio.run(_run(learner))

    rejected = [event for event in sink.events if event.kind == "rejected"]
    assert rejected
    assert rejected[0].version == "v3"


def test_a_training_failure_is_announced():
    sink = _Sink()
    learner = _learner(None, sink=sink)

    asyncio.run(_run(learner))

    assert [event.kind for event in sink.events] == ["failed"]


def test_a_promotion_failure_is_announced():
    sink = _Sink()
    learner = _learner(_outcome(), sink=sink)
    learner.model_manager.artifacts.promote_version = MagicMock(side_effect=OSError("locked"))

    asyncio.run(_run(learner))

    assert [event.kind for event in sink.events] == ["promotion_failed"]


def test_a_sink_failure_does_not_stop_learning():
    learner = _learner(_outcome(), sink=_Sink(fail=True))

    asyncio.run(_run(learner))

    assert learner.outcomes["xgboost-BTC/USDT-1h"].status == "promoted"


def test_drift_is_detected_with_the_gate_off():
    sink = _Sink()
    settings = {"enabled": True, "min_new_candles": 0, "drift_gate": False}
    learner = _learner(_outcome(), data=_frame(drifted=True), sink=sink, settings=settings)

    asyncio.run(_run(learner))

    assert any(event.kind == "drift_detected" for event in sink.events)


def test_the_cooldown_suppresses_a_second_drift_alert():
    sink = _Sink()
    now = {"value": 1000.0}
    settings = {
        "enabled": True,
        "min_new_candles": 0,
        "drift_gate": False,
        "alert_drift_cooldown_hours": 24,
    }
    learner = _learner(
        _outcome(),
        data=_frame(drifted=True),
        sink=sink,
        clock=lambda: now["value"],
        settings=settings,
    )

    asyncio.run(_run(learner))
    now["value"] += 3600.0
    asyncio.run(_run(learner))
    now["value"] += 24 * 3600.0
    asyncio.run(_run(learner))

    drift_events = [event for event in sink.events if event.kind == "drift_detected"]
    assert len(drift_events) == 2


def test_no_drift_emits_no_drift_alert():
    sink = _Sink()
    settings = {"enabled": True, "min_new_candles": 0, "drift_gate": False}
    learner = _learner(_outcome(), data=_frame(drifted=False), sink=sink, settings=settings)

    asyncio.run(_run(learner))

    assert not any(event.kind == "drift_detected" for event in sink.events)


def test_no_sink_means_no_error():
    learner = _learner(_outcome(), sink=None)

    asyncio.run(_run(learner))

    assert learner.outcomes["xgboost-BTC/USDT-1h"].status == "promoted"
