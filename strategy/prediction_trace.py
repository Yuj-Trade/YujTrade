import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.logger import logger

TRACE_SCHEMA_VERSION = 1
UNSAFE_CHARACTERS = ("/", "\\", "|", ":", "*", "?", '"', "<", ">", " ")


def safe_trace_name(signal_id: str) -> str:
    name = signal_id
    for character in UNSAFE_CHARACTERS:
        name = name.replace(character, "_")
    return name


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class PredictionTraceRecorder:
    def __init__(self, directory: str | Path, enabled: bool = True):
        self._directory = Path(directory)
        self._enabled = bool(enabled)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def directory(self) -> Path:
        return self._directory

    def path_for(self, signal_id: str) -> Path:
        return self._directory / f"{safe_trace_name(signal_id)}.json"

    async def record(self, signal_id: str, payload: dict[str, Any]) -> Path | None:
        if not self._enabled:
            return None
        document = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "signal_id": signal_id,
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            **payload,
        }
        target = self.path_for(signal_id)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write, target, document)
        except (OSError, TypeError, ValueError) as e:
            logger.warning(f"Prediction trace not persisted for {signal_id}: {e}")
            return None
        logger.debug(f"Prediction trace persisted for {signal_id}")
        return target

    def _write(self, target: Path, document: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _jsonable(document)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
