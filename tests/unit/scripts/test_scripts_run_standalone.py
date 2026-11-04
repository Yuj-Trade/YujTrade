import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

SKIPPED = {
    "encrypt_keys.py",
    "probe_exchanges.py",
}

HELPLESS = {
    "exchange_shadow_report.py",
    "seed_exchange_env_names.py",
}


def _project_scripts() -> list[Path]:
    scripts = []
    for path in sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "sys.path.insert" not in text:
            continue
        if any(
            f"from {package}" in text
            for package in ("common", "config", "data", "modeling", "trading", "utils", "services")
        ):
            scripts.append(path)
    return scripts


def test_selected_scripts_run_standalone():
    for path in _project_scripts():
        if path.name in SKIPPED:
            continue
        args = [sys.executable, str(path)]
        if path.name not in HELPLESS:
            args.append("--help")
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=ROOT,
        )
        combined = result.stdout + result.stderr
        assert "ModuleNotFoundError" not in combined, f"{path.name}: {combined[-400:]}"
        assert "ImportError" not in combined, f"{path.name}: {combined[-400:]}"


def test_every_script_with_project_imports_bootstraps_sys_path():
    for path in sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        imports_project = any(
            f"from {package}" in text
            for package in ("common", "config", "data", "modeling", "trading", "utils", "services")
        )
        if not imports_project:
            continue
        assert "sys.path.insert" in text, (
            f"{path.name} imports project code without a sys.path boot"
        )
