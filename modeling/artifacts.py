import json
import shutil
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from common.exceptions import ArtifactIntegrityError

REQUIRED_METADATA_KEYS = (
    "data_start",
    "data_end",
    "feature_list",
    "params",
    "git_commit",
    "library_versions",
    "files_sha256",
)

LIBRARY_PACKAGES = ("numpy", "pandas", "scikit-learn", "xgboost", "tensorflow", "keras")


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unknown"


def _library_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in LIBRARY_PACKAGES:
        try:
            versions[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _files_sha256(files: list[Path]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(files, key=str):
        if path.exists() and path.is_file():
            digests[path.name] = sha256(path.read_bytes()).hexdigest()
    return digests


def build_metadata(
    data: Any,
    feature_list: list[str],
    params: dict[str, Any],
    oos_metrics: dict[str, float],
    source_files: list[Path] | None = None,
) -> dict[str, Any]:
    index = data.index
    return {
        "data_start": index[0].isoformat(),
        "data_end": index[-1].isoformat(),
        "feature_list": list(feature_list),
        "params": dict(params),
        "oos_metrics": dict(oos_metrics),
        "git_commit": _git_commit(),
        "library_versions": _library_versions(),
        "files_sha256": _files_sha256(list(source_files or [])),
    }


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
        provided = dict(metadata or {})
        missing = [key for key in REQUIRED_METADATA_KEYS if not provided.get(key)]
        if missing:
            raise ValueError(f"Artifact metadata missing required keys: {missing}")
        model_root = self.model_dir(model_type, symbol, timeframe)
        version_name = version or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        version_dir = model_root / version_name
        version_dir.mkdir(parents=True, exist_ok=False)
        for source in source_files:
            if source.exists():
                shutil.copy2(source, version_dir / source.name)
        actual_hashes = _files_sha256([version_dir / source.name for source in source_files])
        expected = provided["files_sha256"]
        mismatched = [
            name for name, digest in expected.items() if actual_hashes.get(name) != digest
        ]
        if mismatched:
            raise ValueError(f"Artifact file hash mismatch for: {mismatched}")
        payload = {
            "version": version_name,
            "trained_at_utc": datetime.now(UTC).isoformat(),
            "data_start": provided["data_start"],
            "data_end": provided["data_end"],
            "data_sha256": self._hash_files(source_files),
            "feature_list": provided["feature_list"],
            "params": provided["params"],
            "oos_metrics": provided.get("oos_metrics", {}),
            "git_commit": provided["git_commit"],
            "library_versions": provided["library_versions"],
            "files_sha256": actual_hashes,
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

    def current_version(self, model_type: str, symbol: str, timeframe: str) -> str | None:
        current = self.model_dir(model_type, symbol, timeframe) / "current.json"
        if not current.exists():
            return None
        payload = json.loads(current.read_text(encoding="utf-8"))
        version = payload.get("version")
        return version if isinstance(version, str) else None

    def list_versions(self, model_type: str, symbol: str, timeframe: str) -> list[str]:
        model_root = self.model_dir(model_type, symbol, timeframe)
        if not model_root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in model_root.iterdir()
            if entry.is_dir() and (entry / "metadata.json").exists()
        )

    def version_dir(self, model_type: str, symbol: str, timeframe: str, version: str) -> Path:
        directory = self.model_dir(model_type, symbol, timeframe) / version
        if not directory.is_dir():
            raise FileNotFoundError(f"Artifact version does not exist: {directory}")
        return directory

    def read_metadata(
        self, model_type: str, symbol: str, timeframe: str, version: str | None = None
    ) -> dict[str, Any] | None:
        if version is None:
            directory = self.current_dir(model_type, symbol, timeframe)
        else:
            directory = self.version_dir(model_type, symbol, timeframe, version)
        if directory is None:
            return None
        metadata_path = directory / "metadata.json"
        if not metadata_path.exists():
            return None
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    def promote_version(self, model_type: str, symbol: str, timeframe: str, version: str) -> Path:
        directory = self.version_dir(model_type, symbol, timeframe, version)
        if not (directory / "metadata.json").exists():
            raise FileNotFoundError(f"Artifact metadata missing: {directory}")
        pointer = self.model_dir(model_type, symbol, timeframe) / "current.json"
        pointer.write_text(json.dumps({"version": version}, indent=2), encoding="utf-8")
        return directory

    def verify_current(self, model_type: str, symbol: str, timeframe: str) -> Path | None:
        directory = self.current_dir(model_type, symbol, timeframe)
        if directory is None:
            return None
        metadata_path = directory / "metadata.json"
        if not metadata_path.exists():
            raise ArtifactIntegrityError(f"Artifact metadata missing: {metadata_path}")
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected = payload.get("files_sha256")
        if not isinstance(expected, dict) or not expected:
            raise ArtifactIntegrityError(f"Artifact has no file hashes: {metadata_path}")
        mismatched = []
        for name, digest in expected.items():
            candidate = directory / name
            if not candidate.is_file() or sha256(candidate.read_bytes()).hexdigest() != digest:
                mismatched.append(name)
        if mismatched:
            raise ArtifactIntegrityError(
                f"Artifact integrity check failed for {model_type}:{symbol}:{timeframe}: "
                f"{mismatched}"
            )
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
