"""Run the protected local holdout evaluation.

This command intentionally accepts only a local OHLCV CSV. It never fetches
market data and records the data/config hashes before allowing a rerun.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtesting.walk_forward import HoldoutGuard


def run_holdout(
    data_path: str | Path,
    state_path: str | Path,
    confirm: bool = False,
    force_rerun: bool = False,
) -> dict[str, object]:
    path = Path(data_path)
    data = pd.read_csv(path, index_col=0, parse_dates=True)
    guard = HoldoutGuard(
        data,
        state_path=state_path,
        config={"data_path": str(path.resolve()), "holdout_fraction": 0.15},
    )
    holdout = guard.consume(confirm=confirm, force_rerun=force_rerun)
    close = holdout["close"].astype(float)
    result = {
        "rows": int(len(holdout)),
        "data_hash": guard.data_hash,
        "config_hash": guard.config_hash,
        "start": holdout.index[0].isoformat(),
        "end": holdout.index[-1].isoformat(),
        "return": float(close.iloc[-1] / close.iloc[0] - 1.0),
        "forced": force_rerun,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the protected local holdout.")
    parser.add_argument("data", type=Path, help="Local OHLCV CSV")
    parser.add_argument("--state", type=Path, default=Path("runs/holdout_used.json"))
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()
    result = run_holdout(args.data, args.state, args.confirm, args.force_rerun)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
