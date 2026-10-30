"""The read-only learning artifact review (P8)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from modeling.artifacts import ArtifactRegistry, build_metadata
from scripts.review_learning_artifacts import main, render_review, review_artifacts


def _artifact(root: Path, model_type="xgboost", symbol="BTC/USDT", timeframe="1h") -> Path:
    source = root / "src" / f"{model_type}.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("{}", encoding="utf-8")
    frame = pd.DataFrame(
        {"close": [1.0, 2.0]},
        index=pd.date_range("2024-01-01", periods=2, tz="UTC"),
    )
    metadata = build_metadata(frame, ["close"], {"p": 1}, {"rmse": 0.1}, source_files=[source])
    registry = ArtifactRegistry(root / "artifacts")
    return registry.create_version(model_type, symbol, timeframe, [source], metadata=metadata)


def test_a_verified_tree_exits_zero(tmp_path):
    _artifact(tmp_path)

    code, reviews = review_artifacts(tmp_path / "artifacts")

    assert code == 0
    assert reviews
    assert all(review["status"] == "verified" for review in reviews)


def test_a_tampered_file_exits_one(tmp_path):
    version = _artifact(tmp_path)
    model_file = next(version.glob("xgboost*.json"))
    model_file.write_text('{"tampered": true}', encoding="utf-8")

    code, reviews = review_artifacts(tmp_path / "artifacts")

    assert code == 1
    assert any(review["status"] == "failed" for review in reviews)


def test_an_empty_tree_exits_one(tmp_path):
    code, reviews = review_artifacts(tmp_path / "missing")

    assert code == 1
    assert reviews == []


def test_the_review_is_never_promoting(tmp_path):
    version = _artifact(tmp_path)
    before = (version.parent / "current.json").read_text(encoding="utf-8")

    review_artifacts(tmp_path / "artifacts")

    assert (version.parent / "current.json").read_text(encoding="utf-8") == before


def test_the_renderer_reports_the_result():
    text = render_review([], 1)
    assert "No current artifact" in text
    assert "Continuous learning must stay off" in text


def test_the_second_version_is_compared_with_the_previous(tmp_path):
    first = _artifact(tmp_path)
    source = tmp_path / "src" / "xgboost.json"
    frame = pd.DataFrame(
        {"close": [1.0, 2.0]},
        index=pd.date_range("2024-01-01", periods=2, tz="UTC"),
    )
    metadata = build_metadata(frame, ["close"], {"p": 2}, {}, source_files=[source])
    registry = ArtifactRegistry(tmp_path / "artifacts")
    second = registry.create_version("xgboost", "BTC/USDT", "1h", [source], metadata=metadata)

    code, reviews = review_artifacts(tmp_path / "artifacts")

    assert code == 0
    assert reviews[0]["previous_version"] == first.name
    assert reviews[0]["version"] == second.name


def test_the_cli_writes_the_document(tmp_path, monkeypatch, capsys):
    _artifact(tmp_path)
    out = tmp_path / "review.md"
    monkeypatch.setattr(
        "sys.argv",
        ["review_learning_artifacts.py", str(tmp_path / "artifacts"), str(out)],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    assert out.exists()
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["exit_code"] == 0
