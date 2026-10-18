import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

REMOVED = ("scripts/run_golden.py", "scripts/install_mock.py", "symtemp.txt")

REMOVED_METHODS = (
    "get_exchange_info",
    "get_all_futures_symbols",
    "get_circulating_supply",
    "get_all_assets",
    "mtf_analysis_key",
)


def _tracked() -> list[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


def test_removed_files_are_not_tracked():
    tracked = _tracked()
    for name in REMOVED:
        assert name not in tracked, name


def test_removed_fetcher_methods_stay_gone():
    offenders = []
    for name in _tracked():
        if not name.endswith(".py") or name.startswith("tests/"):
            continue
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        for method in REMOVED_METHODS:
            if f"def {method}" in text or f".{method}(" in text:
                offenders.append(f"{name} references {method}")
    assert offenders == []


def test_no_references_to_removed_files():
    offenders = []
    for name in _tracked():
        if not name.endswith((".py", ".md", ".yml", ".yaml", ".txt", ".json")):
            continue
        if name in (
            "docs/open_issues.md",
            "IMPROVEMENT_REPORT.md",
            "tests/unit/scripts/test_dead_code_guard.py",
        ):
            continue
        stem = Path(name).stem
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        for removed in REMOVED:
            if Path(removed).stem in text and Path(removed).stem != stem:
                offenders.append(f"{name} references {removed}")
    assert offenders == []


def test_config_json_stays_untracked():
    tracked = _tracked()
    assert "config.json" not in tracked
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "config.json" in gitignore


def test_backtrader_neither_declared_nor_imported():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "backtrader" not in requirements
    offenders = []
    for name in _tracked():
        if not name.endswith(".py") or name.startswith(("tests/", "skills/", "copyfile/", "Main/")):
            continue
        text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
        if "import backtrader" in text or "from backtrader" in text:
            offenders.append(name)
    assert offenders == []
