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
