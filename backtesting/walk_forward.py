import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Fold:
    index: int
    train: Sequence[object]
    test: Sequence[object]


class HoldoutGuard:
    def __init__(
        self,
        data: Sequence[object],
        holdout_fraction: float = 0.15,
        state_path: str | Path | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        if not 0 < holdout_fraction < 1:
            raise ValueError("holdout_fraction must be between zero and one")
        cut = int(len(data) * (1.0 - holdout_fraction))
        self.development = data[:cut]
        self.holdout = data[cut:]
        self.used = False
        self.state_path = Path(state_path) if state_path else None
        self.data_hash = self._hash_data(self.holdout)
        self.config_hash = self._hash_data(config or {})
        self._state = self._load_state()
        self.used = bool(self._state.get(self.data_hash))

    def consume(self, confirm: bool = False, force_rerun: bool = False) -> Sequence[object]:
        if not confirm:
            raise PermissionError("holdout execution requires explicit confirmation")
        if self.used and not force_rerun:
            raise RuntimeError("holdout already consumed for this guard")
        self.used = True
        self._state[self.data_hash] = {
            "config_hash": self.config_hash,
            "forced": force_rerun,
        }
        self._save_state()
        return self.holdout

    def _load_state(self) -> dict[str, Any]:
        if self.state_path is None or not self.state_path.exists():
            return {}
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid holdout state: {self.state_path}")
        return payload

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def _hash_data(value: Any) -> str:
        if hasattr(value, "to_json"):
            serialized = value.to_json(date_format="iso", orient="split")
        else:
            serialized = json.dumps(value, default=str, sort_keys=True)
        return sha256(serialized.encode("utf-8")).hexdigest()


class WalkForwardValidator:
    def __init__(
        self,
        folds: int = 5,
        min_train_fraction: float = 0.6,
        label_horizon: int = 1,
        warmup_bars: int = 0,
        sequence_length: int = 0,
    ) -> None:
        self.folds = folds
        self.min_train_fraction = min_train_fraction
        self.label_horizon = label_horizon
        self.warmup_bars = warmup_bars
        self.sequence_length = sequence_length

    def split(self, data: Sequence[object]) -> list[Fold]:
        size = len(data)
        minimum = int(size * self.min_train_fraction)
        if self.folds < 1 or minimum <= 0 or minimum >= size:
            raise ValueError("invalid walk-forward configuration")
        test_size = (size - minimum) // self.folds
        if test_size < 1:
            raise ValueError("not enough data for requested folds")
        embargo = max(self.warmup_bars, self.sequence_length)
        result: list[Fold] = []
        for index in range(self.folds):
            train_boundary = minimum + index * test_size
            test_start = train_boundary + embargo
            test_end = size if index == self.folds - 1 else test_start + test_size
            train_end = max(0, train_boundary - self.label_horizon)
            if test_start >= size:
                break
            if hasattr(data, "iloc"):
                train = data.iloc[:train_end]
                test = data.iloc[test_start : min(test_end, size)]
            else:
                train = data[:train_end]
                test = data[test_start : min(test_end, size)]
            result.append(Fold(index, train, test))
        return result
