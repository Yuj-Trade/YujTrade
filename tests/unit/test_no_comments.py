import ast
import io
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _production_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [
        ROOT / name
        for name in listed
        if not name.startswith(("tests/", "skills/", "copyfile/", "Main/"))
    ]


def _allowed_comment(text: str) -> bool:
    lowered = text.lower()
    return (
        "noqa" in lowered
        or "type:" in lowered
        or "pragma" in lowered
        or text.startswith("#!")
        or "coding" in lowered
    )


def test_no_comments_in_production_code():
    offenders = []
    for path in _production_files():
        tokens = tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT and not _allowed_comment(token.string):
                offenders.append(f"{path.relative_to(ROOT)}:{token.start[0]}: {token.string[:80]}")
    assert offenders == []


def test_no_docstrings_in_production_code():
    offenders = []
    for path in _production_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.body[0].lineno}")
    assert offenders == []
