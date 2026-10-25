import asyncio

import pandas as pd

from modeling.learner import LearningSettings, ModelLearner
from modeling.model_manager import TrainingOutcome


class FakeConfig:
    def __init__(self, **overrides):
        self.values = {
            "model_learning": {
                "enabled": True,
                "model_types": ["xgboost"],
                "min_interval_minutes": 60,
                "min_new_candles": 10,
                "max_concurrency": 2,
                "promote": True,
                "drift_gate": False,
            },
            **overrides,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeArtifacts:
    def __init__(self, baseline_metrics=None, promote_error=None):
        self.baseline_metrics = baseline_metrics or {}
        self.promote_error = promote_error
        self.promoted: list[tuple] = []

    def read_metadata(self, model_type, symbol, timeframe):
        return {"oos_metrics": dict(self.baseline_metrics)} if self.baseline_metrics else {}

    def promote_version(self, model_type, symbol, timeframe, version):
        if self.promote_error:
            raise self.promote_error
        self.promoted.append((model_type, symbol, timeframe, version))


class FakeModelManager:
    def __init__(self, artifacts, outcome=None, gate=None, error=None):
        self.artifacts = artifacts
        self.outcome = outcome
        self.gate = gate
        self.error = error
        self.calls: list[dict] = []

    async def train_model(
        self, model_type, symbol, timeframe, data, promote=True, warm_start=False, **kwargs
    ):
        self.calls.append(
            {
                "model_type": model_type,
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": len(data),
                "promote": promote,
                "warm_start": warm_start,
            }
        )
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.outcome


class FakeDataProvider:
    def __init__(self, rows=500, gate=None):
        self.rows = rows
        self.gate = gate
        self.calls = 0

    async def get_data_for_model(self, symbol, timeframe, for_prediction=False):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        index = pd.date_range("2024-01-01", periods=self.rows, freq="h", tz="UTC")
        return pd.DataFrame(
            {
                "open": [100.0] * self.rows,
                "high": [101.0] * self.rows,
                "low": [99.0] * self.rows,
                "close": [100.5] * self.rows,
                "volume": [10.0] * self.rows,
            },
            index=index,
        )


def _outcome(oos_metrics, version="v2"):
    return TrainingOutcome(
        model_type="xgboost",
        symbol="BTC/USDT",
        timeframe="1h",
        version=version,
        promoted=False,
        oos_metrics=oos_metrics,
        artifact_path=f"artifacts/btcusdt/1h/xgboost/{version}",
    )


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def _learner(config=None, artifacts=None, manager=None, provider=None, clock=None):
    artifacts = artifacts or FakeArtifacts()
    manager = manager or FakeModelManager(artifacts, outcome=_outcome({"rmse": 1.0}))
    provider = provider or FakeDataProvider()
    return ModelLearner(manager, provider, config or FakeConfig(), clock=clock or Clock())


def test_settings_come_from_configuration():
    settings = LearningSettings.from_config(
        FakeConfig(model_learning={"enabled": True, "min_interval_minutes": 15})
    )

    assert settings.enabled is True
    assert settings.min_interval_minutes == 15
    assert settings.model_types == ("xgboost",)


async def test_disabled_learner_schedules_nothing():
    learner = _learner(config=FakeConfig(model_learning={"enabled": False}))

    assert learner.request("BTC/USDT", "1h") == []
    assert learner.pending == 0


async def test_request_returns_before_training_completes():
    gate = asyncio.Event()
    provider = FakeDataProvider(gate=gate)
    learner = _learner(provider=provider)

    scheduled = learner.request("BTC/USDT", "1h")

    assert scheduled == ["xgboost-BTC/USDT-1h"]
    assert learner.pending == 1

    gate.set()
    await learner.drain()
    assert learner.pending == 0


async def test_one_job_per_key():
    gate = asyncio.Event()
    provider = FakeDataProvider(gate=gate)
    learner = _learner(provider=provider)

    assert learner.request("BTC/USDT", "1h") == ["xgboost-BTC/USDT-1h"]
    assert learner.request("BTC/USDT", "1h") == []

    gate.set()
    await learner.drain()
    assert provider.calls == 1


async def test_minimum_interval_blocks_a_second_attempt():
    clock = Clock()
    provider = FakeDataProvider()
    learner = _learner(provider=provider, clock=clock)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    clock.now += 60
    assert learner.request("BTC/USDT", "1h") == []

    clock.now += 3600
    assert learner.request("BTC/USDT", "1h") == ["xgboost-BTC/USDT-1h"]
    await learner.drain()


async def test_rejections_back_off_the_interval():
    clock = Clock()
    artifacts = FakeArtifacts(baseline_metrics={"directional_accuracy": 0.8, "rmse": 1.0})
    manager = FakeModelManager(
        artifacts, outcome=_outcome({"directional_accuracy": 0.2, "rmse": 1.0})
    )
    learner = _learner(artifacts=artifacts, manager=manager, clock=clock)

    learner.request("BTC/USDT", "1h")
    await learner.drain()
    assert learner.outcomes["xgboost-BTC/USDT-1h"].status == "rejected"

    clock.now += 3601
    assert learner.request("BTC/USDT", "1h") == []

    clock.now += 3600
    assert learner.request("BTC/USDT", "1h") == ["xgboost-BTC/USDT-1h"]
    await learner.drain()


async def test_minimum_new_candles_gate():
    clock = Clock()
    provider = FakeDataProvider(rows=500)
    artifacts = FakeArtifacts()
    manager = FakeModelManager(artifacts, outcome=_outcome({"rmse": 1.0}))
    learner = _learner(artifacts=artifacts, manager=manager, provider=provider, clock=clock)

    learner.request("BTC/USDT", "1h")
    await learner.drain()
    assert len(manager.calls) == 1

    clock.now += 7200
    provider.rows = 505
    learner.request("BTC/USDT", "1h")
    await learner.drain()
    assert len(manager.calls) == 1

    clock.now += 7200
    provider.rows = 520
    learner.request("BTC/USDT", "1h")
    await learner.drain()
    assert len(manager.calls) == 2


async def test_training_is_warm_started_and_not_promoted_inline():
    artifacts = FakeArtifacts()
    manager = FakeModelManager(artifacts, outcome=_outcome({"rmse": 1.0}))
    learner = _learner(artifacts=artifacts, manager=manager)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    assert manager.calls[0]["warm_start"] is True
    assert manager.calls[0]["promote"] is False


async def test_degraded_candidate_is_not_promoted():
    artifacts = FakeArtifacts(baseline_metrics={"directional_accuracy": 0.8, "rmse": 1.0})
    manager = FakeModelManager(
        artifacts, outcome=_outcome({"directional_accuracy": 0.1, "rmse": 1.0})
    )
    learner = _learner(artifacts=artifacts, manager=manager)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    assert artifacts.promoted == []
    outcome = learner.outcomes["xgboost-BTC/USDT-1h"]
    assert outcome.status == "rejected"
    assert "directional_accuracy_degraded" in outcome.reasons


async def test_improved_candidate_is_promoted():
    artifacts = FakeArtifacts(baseline_metrics={"directional_accuracy": 0.5, "rmse": 1.0})
    manager = FakeModelManager(
        artifacts, outcome=_outcome({"directional_accuracy": 0.9, "rmse": 0.9})
    )
    learner = _learner(artifacts=artifacts, manager=manager)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    assert artifacts.promoted == [("xgboost", "BTC/USDT", "1h", "v2")]
    assert learner.outcomes["xgboost-BTC/USDT-1h"].status == "promoted"


async def test_first_ever_model_is_promoted_without_a_baseline():
    artifacts = FakeArtifacts()
    manager = FakeModelManager(artifacts, outcome=_outcome({"rmse": 1.0}))
    learner = _learner(artifacts=artifacts, manager=manager)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    assert artifacts.promoted == [("xgboost", "BTC/USDT", "1h", "v2")]


async def test_promotion_failure_is_contained():
    artifacts = FakeArtifacts(promote_error=OSError("disk full"))
    manager = FakeModelManager(artifacts, outcome=_outcome({"rmse": 1.0}))
    learner = _learner(artifacts=artifacts, manager=manager)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    assert learner.outcomes["xgboost-BTC/USDT-1h"].status == "promotion_failed"


async def test_training_failure_is_isolated():
    artifacts = FakeArtifacts()
    manager = FakeModelManager(artifacts, error=RuntimeError("boom"))
    learner = _learner(artifacts=artifacts, manager=manager)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    assert learner.outcomes["xgboost-BTC/USDT-1h"].status == "failed"
    assert learner.pending == 0


async def test_promotion_can_be_disabled():
    artifacts = FakeArtifacts()
    manager = FakeModelManager(artifacts, outcome=_outcome({"rmse": 1.0}))
    config = FakeConfig(
        model_learning={"enabled": True, "model_types": ["xgboost"], "promote": False}
    )
    learner = _learner(config=config, artifacts=artifacts, manager=manager)

    learner.request("BTC/USDT", "1h")
    await learner.drain()

    assert artifacts.promoted == []
    assert learner.outcomes["xgboost-BTC/USDT-1h"].status == "rejected"


async def test_shutdown_cancels_pending_jobs():
    gate = asyncio.Event()
    provider = FakeDataProvider(gate=gate)
    learner = _learner(provider=provider)

    learner.request("BTC/USDT", "1h")
    await learner.shutdown()

    assert learner.pending == 0


def test_prediction_still_never_trains():
    from config.settings import ConfigManager

    assert ConfigManager.DEFAULT_CONFIG.get("model_auto_train_on_predict") is False
