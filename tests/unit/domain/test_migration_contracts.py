from datetime import datetime, timedelta, timezone

from backtesting.walk_forward import HoldoutGuard, WalkForwardValidator
from domain.outcome import resolve_outcome
from modeling.artifacts import ArtifactRegistry


def test_walk_forward_applies_purge_and_embargo():
    folds = WalkForwardValidator(
        folds=2,
        min_train_fraction=0.5,
        label_horizon=1,
        warmup_bars=2,
        sequence_length=3,
    ).split(list(range(20)))

    assert len(folds) == 2
    assert len(folds[0].train) == 9
    assert folds[0].test[0] == 13


def test_holdout_requires_confirmation_and_is_idempotency_guarded():
    guard = HoldoutGuard(list(range(20)), holdout_fraction=0.2)
    assert list(guard.consume(confirm=True)) == list(range(16, 20))

    try:
        guard.consume(confirm=True)
    except RuntimeError:
        pass
    else:
        raise AssertionError("holdout was consumed twice")


def test_outcome_stop_first_matches_paper_resolution():
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = resolve_outcome(
        [
            {
                "timestamp": created + timedelta(hours=1),
                "high": 110,
                "low": 90,
            }
        ],
        "buy",
        100,
        95,
        105,
    )

    assert result is not None
    assert result.reason == "stop"


def test_artifact_registry_persists_current_pointer_and_calibration(tmp_path):
    source = tmp_path / "model.json"
    source.write_text("{}", encoding="utf-8")
    registry = ArtifactRegistry(tmp_path / "artifacts")
    version = registry.create_version("xgboost", "BTC/USDT", "1h", [source])

    assert registry.current_dir("xgboost", "BTC/USDT", "1h") == version
    registry.save_calibration("xgboost", "BTC/USDT", "1h", [(80.0, True, 1.0)])
    assert registry.load_calibration("xgboost", "BTC/USDT", "1h") == [(80.0, True, 1.0)]
