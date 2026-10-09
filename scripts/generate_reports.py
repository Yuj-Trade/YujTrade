"""Generate reproducible local environment and baseline reports."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_revision() -> str | None:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            )
            .strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def build_report(root: Path) -> dict[str, Any]:
    baseline = root / "tests" / "golden" / "signals_baseline.json"
    baseline_payload: Any = None
    if baseline.exists():
        baseline_payload = json.loads(baseline.read_text(encoding="utf-8"))
    baseline_items = len(baseline_payload) if isinstance(baseline_payload, list) else None
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "git_revision": _git_revision(),
        "baseline": {
            "path": str(baseline.relative_to(root)),
            "sha256": _sha256(baseline) if baseline.exists() else None,
            "items": baseline_items,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/environment-baseline.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_report(root), indent=2, sort_keys=True), encoding="utf-8"
    )
    print(output)


if __name__ == "__main__":
    main()
