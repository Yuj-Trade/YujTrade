import json
import shutil
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


class ArtifactRegistry:
    def __init__(self, root: str | Path = "artifacts") -> None:
        self.root = Path(root)

    def model_dir(self, model_type: str, symbol: str, timeframe: str) -> Path:
        safe_symbol = symbol.lower().replace("/", "")
        return self.root / safe_symbol / timeframe / model_type

    def create_version(
        self,
        model_type: str,
        symbol: str,
        timeframe: str,
        source_files: list[Path],
        metadata: dict[str, Any] | None = None,
        version: str | None = None,
        update_current: bool = True,
    ) -> Path:
        model_root = self.model_dir(model_type, symbol, timeframe)
        version_name = version or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        version_dir = model_root / version_name
        version_dir.mkdir(parents=True, exist_ok=False)
        for source in source_files:
            if source.exists():
                shutil.copy2(source, version_dir / source.name)
        payload = {
            "version": version_name,
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "data_start": None,
            "data_end": None,
            "data_sha256": self._hash_files(source_files),
            "feature_list": [],
            "params": {},
            "oos_metrics": {},
            "git_commit": None,
            "library_versions": {},
            **(metadata or {}),
        }
        (version_dir / "metadata.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        (version_dir / "calibration.json").write_text(
            json.dumps({"model": f"{model_type}:{symbol}:{timeframe}", "samples": []}, indent=2),
            encoding="utf-8",
        )
        if update_current:
            (model_root / "current.json").write_text(
                json.dumps({"version": version_name}, indent=2), encoding="utf-8"
            )
        return version_dir

    def current_dir(self, model_type: str, symbol: str, timeframe: str) -> Path | None:
        current = self.model_dir(model_type, symbol, timeframe) / "current.json"
        if not current.exists():
            return None
        payload = json.loads(current.read_text(encoding="utf-8"))
        version = payload.get("version")
        if not isinstance(version, str):
            raise ValueError(f"Invalid current artifact pointer: {current}")
        directory = current.parent / version
        if not directory.is_dir():
            raise FileNotFoundError(f"Artifact version does not exist: {directory}")
        return directory

    def save_calibration(
        self,
        model_type: str,
        symbol: str,
        timeframe: str,
        samples: list[tuple[float, bool, float]],
    ) -> None:
        directory = self.current_dir(model_type, symbol, timeframe)
        if directory is None:
            return
        (directory / "calibration.json").write_text(
            json.dumps(
                {
                    "model": f"{model_type}:{symbol}:{timeframe}",
                    "samples": [
                        {"confidence": c, "success": ok, "weight": weight}
                        for c, ok, weight in samples
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def load_calibration(
        self, model_type: str, symbol: str, timeframe: str
    ) -> list[tuple[float, bool, float]]:
        directory = self.current_dir(model_type, symbol, timeframe)
        if directory is None:
            return []
        path = directory / "calibration.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [
            (float(item["confidence"]), bool(item["success"]), float(item["weight"]))
            for item in payload.get("samples", [])
        ]

    @staticmethod
    def _hash_files(files: list[Path]) -> str:
        digest = sha256()
        for path in sorted(files, key=str):
            if path.exists():
                digest.update(path.read_bytes())
        return digest.hexdigest()
