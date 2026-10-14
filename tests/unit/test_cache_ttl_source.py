import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _production_files(*packages: str) -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / name for name in listed if name.split("/")[0] in packages]


def test_no_integer_ttl_literals_in_cache_writes():
    offenders = []
    for path in _production_files("data", "strategy"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "ex":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_no_integer_cache_ttl_attribute():
    offenders = []
    for path in _production_files("data", "strategy"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign | ast.Assign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, int):
                    names = {target.attr for target in targets if isinstance(target, ast.Attribute)}
                    if "cache_ttl" in names:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []
