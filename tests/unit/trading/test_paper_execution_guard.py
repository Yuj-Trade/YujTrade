import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN_PREFIXES = (
    "trading.exchanges",
    "trading.execution",
)
FORBIDDEN_NAMES = {"ExchangeAdapter", "ExecutionEngine"}
PAPER_PATH_MODULES = (
    "trading/paper_trading.py",
    "application/performance_report.py",
    "trading/portfolio.py",
    "trading/risk_manager.py",
)
SERVICE_MODULE = "services/trading_service.py"
PAPER_ENTRYPOINTS = {"execute_signal", "resolve_open_paper_positions", "rehydrate_paper_positions"}


def _module_path(relative: str) -> Path:
    return ROOT / relative


def _paper_entrypoints() -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    tree = ast.parse(_module_path("services/trading_service.py").read_text(encoding="utf-8"))
    found: list[ast.AsyncFunctionDef | ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in (
            PAPER_ENTRYPOINTS
        ):
            found.append(node)
    return found


def _imports_in(node: ast.AST) -> list[str]:
    offenders: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                if any(alias.name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                    offenders.append(alias.name)
                if alias.name in FORBIDDEN_NAMES:
                    offenders.append(alias.name)
        elif isinstance(child, ast.ImportFrom):
            module = child.module or ""
            if any(module.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
                offenders.append(module)
            for alias in child.names:
                if alias.name in FORBIDDEN_NAMES:
                    offenders.append(f"{module}.{alias.name}")
    return offenders


def test_the_paper_modules_do_not_import_the_exchange_layer():
    offenders: list[str] = []
    for relative in PAPER_PATH_MODULES:
        tree = ast.parse(_module_path(relative).read_text(encoding="utf-8"))
        offenders.extend(f"{relative}: {name}" for name in _imports_in(tree))
    assert offenders == []


def test_the_service_reaches_the_exchange_layer_only_inside_functions():
    tree = ast.parse(_module_path(SERVICE_MODULE).read_text(encoding="utf-8"))
    module_level: list[str] = []
    nested: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        module_level.extend(_imports_in(node))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested.extend(_imports_in(node))
    assert all(not item.startswith("trading.exchanges") for item in module_level), module_level
    assert any(item.startswith("trading.exchanges") for item in nested), nested


def test_the_paper_entrypoints_are_found():
    names = {node.name for node in _paper_entrypoints()}
    assert names == PAPER_ENTRYPOINTS


def test_the_paper_entrypoints_do_not_reach_the_exchange_layer():
    offenders: list[str] = []
    for node in _paper_entrypoints():
        offenders.extend(f"{node.name}: {name}" for name in _imports_in(node))
    assert offenders == []


def test_the_paper_entrypoints_do_not_name_exchange_components():
    offenders: list[str] = []
    for node in _paper_entrypoints():
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in FORBIDDEN_NAMES:
                offenders.append(f"{node.name}: uses {child.id}")
            if isinstance(child, ast.Attribute) and child.attr in FORBIDDEN_NAMES:
                offenders.append(f"{node.name}: uses {child.attr}")
    assert offenders == []
