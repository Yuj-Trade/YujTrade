"""Docker HEALTHCHECK probe: verify the image can boot its config layer.

Light by design: imports only (no network, no trades, no scheduler).
Exit 0 = healthy, exit 1 = unhealthy.
"""

import sys
from pathlib import Path

# Allow `python scripts/docker_healthcheck.py` from the repo root / WORKDIR:
# script-dir lands on sys.path, so add the project root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        import domain.types  # noqa: F401
        from config.settings import SecretsManager  # noqa: F401
    except Exception as exc:  # pragma: no cover - defensive probe
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1
    print("healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
