import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.logger import logger
from modeling.artifacts import ArtifactRegistry

DEFAULT_ARTIFACT_ROOT = Path("artifacts")
DEFAULT_OUTPUT = Path("docs/remediation/learning-review-2026-10-29.md")


def _artifact_entries(root: Path) -> list[tuple[str, str, str, str]]:
    entries: list[tuple[str, str, str, str]] = []
    if not root.is_dir():
        return entries
    for symbol_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for timeframe_dir in sorted(path for path in symbol_dir.iterdir() if path.is_dir()):
            for model_dir in sorted(path for path in timeframe_dir.iterdir() if path.is_dir()):
                entries.append((model_dir.name, symbol_dir.name, timeframe_dir.name, ""))
    return entries


def _previous_version(registry: ArtifactRegistry, model_type, symbol, timeframe, current) -> str:
    versions = registry.list_versions(model_type, symbol, timeframe)
    if current not in versions:
        return ""
    index = versions.index(current)
    return versions[index - 1] if index > 0 else ""


def review_artifacts(root: Path = DEFAULT_ARTIFACT_ROOT) -> tuple[int, list[dict[str, Any]]]:
    registry = ArtifactRegistry(root)
    reviews: list[dict[str, Any]] = []
    failures = 0
    for model_type, symbol, timeframe, _ in _artifact_entries(root):
        entry: dict[str, Any] = {
            "model_type": model_type,
            "symbol": symbol,
            "timeframe": timeframe,
        }
        try:
            directory = registry.verify_current(model_type, symbol, timeframe)
            if directory is None:
                entry["status"] = "missing_current"
                failures += 1
                reviews.append(entry)
                continue
            version = registry.current_version(model_type, symbol, timeframe) or ""
            metadata = registry.read_metadata(model_type, symbol, timeframe) or {}
            previous = _previous_version(registry, model_type, symbol, timeframe, version)
            entry.update(
                {
                    "status": "verified",
                    "version": version,
                    "previous_version": previous,
                    "data_start": metadata.get("data_start"),
                    "data_end": metadata.get("data_end"),
                    "feature_count": len(metadata.get("feature_list") or []),
                    "oos_metrics": metadata.get("oos_metrics") or {},
                }
            )
            reviews.append(entry)
        except Exception as exc:
            entry.update({"status": "failed", "error": str(exc)})
            failures += 1
            reviews.append(entry)
    if not reviews:
        return 1, []
    return (0 if failures == 0 else 1), reviews


def render_review(reviews: list[dict[str, Any]], exit_code: int) -> str:
    lines = [
        "# Continuous learning artifact review (2026-10-29)",
        "",
        "Read-only review produced by `scripts/review_learning_artifacts.py`.",
        "It never promotes or modifies an artifact.",
        "",
        f"- exit code: `{exit_code}`",
        f"- current artifacts reviewed: `{len(reviews)}`",
        f"- generated at: `{datetime.now(UTC).isoformat()}`",
        "",
        "## Artifacts",
        "",
        "| symbol | timeframe | model | status | version | previous | data_end |",
        "|---|---|---|---|---|---|---|",
    ]
    for review in reviews:
        lines.append(
            "| {symbol} | {timeframe} | {model_type} | {status} | {version} | "
            "{previous_version} | {data_end} |".format(
                symbol=review.get("symbol", ""),
                timeframe=review.get("timeframe", ""),
                model_type=review.get("model_type", ""),
                status=review.get("status", ""),
                version=review.get("version", ""),
                previous_version=review.get("previous_version", ""),
                data_end=review.get("data_end", ""),
            )
        )
    failures = [review for review in reviews if review.get("status") != "verified"]
    lines.extend(["", "## Result", ""])
    if exit_code == 0:
        lines.append("Every current artifact verifies. Continuous learning may be enabled locally.")
    elif not reviews:
        lines.append("No current artifact exists. Continuous learning must stay off.")
    else:
        lines.append(
            f"{len(failures)} artifact(s) did not verify. Continuous learning must stay off."
        )
        for review in failures:
            lines.append(
                f"- {review.get('symbol')} {review.get('timeframe')} "
                f"{review.get('model_type')}: {review.get('status')} "
                f"{review.get('error', '')}".rstrip()
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ARTIFACT_ROOT
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    exit_code, reviews = review_artifacts(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_review(reviews, exit_code), encoding="utf-8")
    logger.info(f"Learning artifact review written to {out}")
    print(json.dumps({"exit_code": exit_code, "artifacts": len(reviews)}))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
