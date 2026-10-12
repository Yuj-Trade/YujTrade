"""Clean-architecture dependency rule enforced with `ast` (no new dependencies).

- `domain` depends on the standard library (and itself) only.
- `application` depends on `domain` and the standard library (and itself) only.

Any import reaching outward (infrastructure, app, services, ...) fails here.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STDLIB = set(sys.stdlib_module_names)

DOMAIN_ALLOW = set()
APPLICATION_ALLOW = {"domain"}


def _external_imports(package: str, extra_allow: set[str]) -> list[str]:
    violations = []
    for path in sorted((ROOT / package).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in STDLIB and top != package and top not in extra_allow:
                        violations.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > 1:
                        violations.append(
                            f"{path.name}: relative import climbs out ({node.module})"
                        )
                    continue
                top = (node.module or "").split(".")[0]
                if top and top not in STDLIB and top != package and top not in extra_allow:
                    violations.append(f"{path.name}: from {node.module} import ...")
    return violations


def test_domain_imports_only_stdlib():
    assert _external_imports("domain", DOMAIN_ALLOW) == []


def test_application_imports_only_domain_and_stdlib():
    assert _external_imports("application", APPLICATION_ALLOW) == []


FORBIDDEN_SERIALIZATION_IMPORTS = {"pickle", "dill", "cloudpickle"}
FORBIDDEN_JOBLIB_LOADS = {"load"}


def _serialization_violations() -> list[str]:
    violations = []
    roots = [ROOT]
    for base in roots:
        for path in sorted(base.rglob("*.py")):
            try:
                relative = path.relative_to(ROOT)
            except ValueError:
                continue
            parts = relative.parts
            if parts[0] in {"tests", "Main", "skills", "copyfile"}:
                continue
            if parts[0].startswith("."):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in FORBIDDEN_SERIALIZATION_IMPORTS:
                            violations.append(f"{relative}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = (node.module or "").split(".")[0]
                    if module in FORBIDDEN_SERIALIZATION_IMPORTS:
                        violations.append(f"{relative}: from {node.module} import ...")
                    if module == "joblib" and any(
                        alias.name in FORBIDDEN_JOBLIB_LOADS for alias in node.names
                    ):
                        violations.append(f"{relative}: from joblib import load")
                elif isinstance(node, ast.Attribute):
                    if (
                        isinstance(node.value, ast.Name)
                        and node.value.id == "joblib"
                        and node.attr == "load"
                    ):
                        violations.append(f"{relative}: joblib.load usage")
    return violations


def test_no_pickle_or_unsafe_deserialization_in_production_code():
    assert _serialization_violations() == []
