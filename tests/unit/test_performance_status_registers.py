"""Status registers for the code the performance work replaces.

Each test records a fact about the current repository that the following
phases change. They are the "before" side of the change and are replaced by
the guards of phase 8.
"""

import ast
import inspect
import subprocess
from pathlib import Path

from trading.paper_trading import PaperTradingEngine

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).relative_to(ROOT).as_posix()

METRIC_HELPERS = (
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_max_drawdown",
)


def _tracked_python_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [
        ROOT / name
        for name in listed
        if not name.startswith(("Main/", "skills/", "copyfile/")) and name != SELF
    ]


def _production_python_files() -> list[Path]:
    return [
        path
        for path in _tracked_python_files()
        if "tests/" not in path.relative_to(ROOT).as_posix()
    ]


def _trees(paths: list[Path] | None = None) -> list[tuple[Path, ast.Module]]:
    trees = []
    for path in paths if paths is not None else _tracked_python_files():
        trees.append((path, ast.parse(path.read_text(encoding="utf-8"))))
    return trees


def _defined_functions(path: Path) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _referenced_names() -> set[str]:
    referenced: set[str] = set()
    for _path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
    return referenced


def test_the_three_metric_helpers_are_gone_from_common_utils():
    defined = _defined_functions(Path("common/utils.py"))

    for helper in METRIC_HELPERS:
        assert helper not in defined


def test_the_three_metric_helpers_have_no_caller_anywhere():
    referenced = _referenced_names()

    for helper in METRIC_HELPERS:
        assert helper not in referenced


def test_paper_ledger_is_used_by_the_trading_service_only():
    importers = []
    for path, tree in _trees(_production_python_files()):
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "trading.ledger" or (
                    module == "trading" and any(a.name == "PaperLedger" for a in node.names)
                ):
                    importers.append(path.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "trading.ledger":
                        importers.append(path.name)
            elif isinstance(node, ast.Name) and node.id == "PaperLedger":
                importers.append(path.name)
    assert sorted(set(importers)) == ["generate_performance_report.py", "trading_service.py"]


def test_paper_trading_engine_has_no_hard_coded_cost_defaults():
    parameters = inspect.signature(PaperTradingEngine.__init__).parameters

    assert parameters["fee_rate"].default is inspect.Parameter.empty
    assert parameters["slippage_rate"].default is inspect.Parameter.empty


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}" if node.module else alias.name)
    return names


def test_the_three_metric_helpers_are_not_imported_anywhere():
    for helper in METRIC_HELPERS:
        for path in _tracked_python_files():
            imported = _imported_names(path)
            assert not any(name == helper or name.endswith(f".{helper}") for name in imported), (
                f"{path.relative_to(ROOT)} imports {helper}"
            )
