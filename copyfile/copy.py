"""Export the YujTrade source tree into a single AI-reviewable text bundle.

Reads every *necessary* project file (source, config, docs, tests) and
writes them into one ``full-trade.txt`` file. Each file section carries
a metadata header so an LLM can review the source without ambiguity:

- stable posix-style relative path (the identity of the file)
- detected language, size, line/char counts, sha256 (content identity)
- last-modified UTC timestamp (freshness)
- for Python: module docstring, top-level imports and definitions
- explicit truncation / decode-error / skipped-file notices

Skipped on purpose (never part of the bundle):

- VCS, caches, virtualenvs, vendored packages (``.git``, ``Main``,
  ``skills``, ``__pycache__``, ``*.egg-info`` ...).
- Runtime artefacts (``logs``, ``runs``, ``models`` binaries, ``data`` dumps).
- Secrets (``.env``, ``secret.salt``, ``*.pem``/``*.key``).
- The bundle output itself (``copyfile/full-trade.txt``).

Usage:
    python copyfile/copy.py [--root .] [--output full-trade.txt]
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Inclusion / exclusion policy
# ---------------------------------------------------------------------------

# Source packages that make up the product (mirrors pyproject packages.find).
SOURCE_DIRS = {
    "app",
    "analysis",
    "application",
    "backtesting",
    "common",
    "config",
    "data",
    "domain",
    "features",
    "modeling",
    "services",
    "strategy",
    "trading",
    "utils",
    "scripts",
    "tests",
}

# Non-package folders whose text files are still necessary context.
EXTRA_DIRS = {"docs"}

# Root-level files always included when present (AI needs build/entry context).
ROOT_FILES = {
    "main.py",
    "fix_test.py",
    "pyproject.toml",
    "requirements.txt",
    "config.json",
    "indicator_weights.json",
    "symbols.txt",
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "LICENSE",
    "Dockerfile",
    ".dockerignore",
    ".gitignore",
    ".gitattributes",
    ".pre-commit-config.yaml",
    "prompt",
}

# Extension -> language label used in metadata headers.
INCLUDE_EXTS = {
    ".py": "python",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".ini": "ini",
    ".cfg": "cfg",
    ".env.example": "env-example",
    ".sh": "shell",
    ".sql": "sql",
}

# Basenames included regardless of extension ( Docker / licence / manifest ).
INCLUDE_BASENAMES = {
    "dockerfile",
    "makefile",
    "license",
    "requirements.txt",
    ".dockerignore",
    ".gitignore",
    ".gitattributes",
}

IGNORE_DIRS = {
    "__pycache__",
    ".git",
    ".github",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "Main",  # vendored interpreter packages, not project source
    "skills",  # huge prompt library, git-ignored, not project source
    "copyfile",  # the bundle output lives here; handled explicitly
    "logs",
    "runs",
    "models",  # binary artefacts (.pkl/.keras); excluded, listed in manifest
    "openspec",
    "yujtrade.egg-info",
    "docs/_build",
    "htmlcov",
    ".tox",
    ".nox",
    ".hypothesis",
    ".ipynb_checkpoints",
}

# Glob patterns (matched against the posix relative path) that are never bundled.
IGNORE_PATTERNS = (
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.pkl",
    "*.db",
    "*.sqlite3*",
    "*.keras",
    "*.h5",
    "*.pt",
    "*.pth",
    "*.bin",
    "*.onnx",
    "*.egg",
    "*.whl",
    "*.log",
    "copyfile/full-trade.txt",
    "copyfile/__pycache__/*",
)

# Secret-bearing files: never read, only counted in the summary.
SECRET_PATTERNS = (".env", "secret.salt", "*.pem", "*.key", "*.p12", "*.pfx")

# Hard cap per file; larger files are truncated with an explicit notice.
MAX_FILE_BYTES = 512_000

SEPARATOR = "=" * 80
SUB_SEPARATOR = "-" * 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _posix(rel_path: str) -> str:
    return rel_path.replace(os.sep, "/")


def _is_secret(posix_rel: str) -> bool:
    base = posix_rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(base, pat) for pat in SECRET_PATTERNS)


def _is_ignored(posix_rel: str) -> bool:
    parts = posix_rel.split("/")
    if any(part in IGNORE_DIRS for part in parts[:-1]):
        return True
    return any(fnmatch.fnmatch(posix_rel, pat) for pat in IGNORE_PATTERNS)


def _language_for(posix_rel: str) -> str | None:
    base = posix_rel.rsplit("/", 1)[-1].lower()
    if base in INCLUDE_BASENAMES:
        return "config" if base.startswith(".") else "text"
    if base == "dockerfile":
        return "dockerfile"
    _, dot, ext = base.rpartition(".")
    if not dot:
        # Extension-less small files such as `prompt` are still useful context.
        return "text"
    return INCLUDE_EXTS.get("." + ext)


def _read_text(abs_path: str) -> tuple[str, str]:
    """Return (content, notice). Binary/undecodable input never raises."""
    with open(abs_path, "rb") as fh:
        raw = fh.read(MAX_FILE_BYTES + 1)
    notice = ""
    if len(raw) > MAX_FILE_BYTES:
        raw = raw[:MAX_FILE_BYTES]
        notice = f"[TRUNCATED at {MAX_FILE_BYTES} bytes; original is larger] "
    if b"\x00" in raw:
        return "", (notice + "[SKIPPED: binary file]").strip()
    try:
        return raw.decode("utf-8"), notice
    except UnicodeDecodeError:
        note = (notice + " [NOTE: decoded with replacement chars]").strip()
        return raw.decode("utf-8", errors="replace"), note


def _python_structure(content: str) -> dict:
    """Extract docstring / imports / top-level defs via ast (best effort)."""
    info: dict = {"docstring": "", "imports": [], "defines": []}
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return info
    doc = ast.get_docstring(tree)
    if doc:
        info["docstring"] = " ".join(doc.split())[:300]
    for node in tree.body:
        if isinstance(node, ast.Import):
            info["imports"].extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            info["imports"].append(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["defines"].append(f"def {node.name}()")
        elif isinstance(node, ast.ClassDef):
            info["defines"].append(f"class {node.name}")
    # Stable, deduplicated, bounded.
    seen: set[str] = set()
    imports = [i for i in info["imports"] if not (i in seen or seen.add(i))]
    info["imports"] = imports[:30]
    info["defines"] = info["defines"][:40]
    return info


def _collect(root: str) -> tuple[list[dict], list[str], int]:
    """Walk the tree; return (files, secret_skips, binary_skips)."""
    collected: list[dict] = []
    secrets: list[str] = []
    binaries = 0
    visited: set[str] = set()

    def _add(abs_path: str) -> None:
        nonlocal binaries
        rel = os.path.relpath(abs_path, root)
        posix_rel = _posix(rel)
        if posix_rel in visited:
            return
        lang = _language_for(posix_rel)
        if lang is None or _is_ignored(posix_rel):
            return
        if _is_secret(posix_rel):
            secrets.append(posix_rel)
            return
        try:
            st = os.stat(abs_path)
        except OSError:
            return
        if st.st_size == 0:
            content, notice = "", "[EMPTY FILE]"
        else:
            content, notice = _read_text(abs_path)
            if notice == "[SKIPPED: binary file]":
                binaries += 1
                return
        visited.add(posix_rel)
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        entry = {
            "rel": posix_rel,
            "abs": abs_path,
            "language": lang,
            "bytes": st.st_size,
            "lines": content.count("\n") + (1 if content and not content.endswith("\n") else 0),
            "chars": len(content),
            "sha256": sha,
            "short_hash": sha[:12],
            "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "content": content,
            "notice": notice,
            "py": _python_structure(content) if lang == "python" else None,
        }
        collected.append(entry)

    # 1. Whole source / test / doc package directories.
    for top in sorted(SOURCE_DIRS | EXTRA_DIRS):
        top_abs = os.path.join(root, top)
        if not os.path.isdir(top_abs):
            continue
        for folder, dirs, files in os.walk(top_abs):
            dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS)
            for name in sorted(files):
                if name == "__init__.py" and os.path.getsize(os.path.join(folder, name)) == 0:
                    continue  # empty package markers carry no signal
                _add(os.path.join(folder, name))

    # 2. Root-level context files.
    for name in sorted(ROOT_FILES):
        abs_path = os.path.join(root, name)
        if os.path.isfile(abs_path):
            _add(abs_path)

    # 3. The exporter itself, so the bundle documents how it was built.
    _add(os.path.join(root, "copyfile", "copy.py"))

    collected.sort(key=lambda e: e["rel"])
    return collected, sorted(secrets), binaries


def _render_tree(rel_paths: list[str], limit: int = 250) -> list[str]:
    tree: dict = {}
    for rel in rel_paths:
        node = tree
        for part in rel.split("/"):
            node = node.setdefault(part, {})
    lines: list[str] = []

    def _walk(node: dict, prefix: str) -> None:
        for i, key in enumerate(sorted(node)):
            last = i == len(node) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{key}")
            if len(lines) >= limit:
                return
            _walk(node[key], prefix + ("    " if last else "│   "))

    _walk(tree, "")
    if len(rel_paths) > limit:
        lines.append(f"... ({len(rel_paths) - limit} more paths omitted)")
    return lines


# ---------------------------------------------------------------------------
# Bundle writer
# ---------------------------------------------------------------------------


def build_bundle(root_path: str, output_file: str | None = None) -> dict:
    root = os.path.abspath(root_path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = output_file or os.path.join(script_dir, "full-trade.txt")
    generated = datetime.now(timezone.utc).isoformat()
    files, secrets, binary_skips = _collect(root)

    total_lines = sum(f["lines"] for f in files)
    total_chars = sum(f["chars"] for f in files)
    by_lang: dict[str, int] = {}
    for f in files:
        by_lang[f["language"]] = by_lang.get(f["language"], 0) + 1

    with open(output_file, "w", encoding="utf-8") as out:
        out.write("# YujTrade — Full Source Export (single-file AI review bundle)\n")
        out.write(f"# Generated (UTC): {generated}\n")
        out.write(f"# Project root: {root}\n")
        out.write("# Generator: copyfile/copy.py :: build_bundle\n")
        out.write("#\n")
        out.write("# HOW TO READ THIS FILE (instructions for AI reviewers):\n")
        out.write("# - Paths are posix-style, relative to the project root, and unique.\n")
        out.write("# - `sha256` is over the exact bundled content (after decode/truncation\n")
        out.write("#   notices); `short_hash` is its first 12 hex chars.\n")
        out.write("# - Each file body is the literal file content, unmodified except for\n")
        out.write("#   an explicit [TRUNCATED ...] / [NOTE: ...] marker when present.\n")
        out.write("# - `mtime_utc` is informational only; `sha256` is the identity.\n")
        out.write(f"# - Bundle: {len(files)} files, {total_lines} lines, {total_chars} chars.\n")
        out.write(f"{SEPARATOR}\n\n")

        out.write("## TABLE OF CONTENTS\n")
        for i, f in enumerate(files, 1):
            out.write(f"# {i:3d}/{len(files)} | {f['rel']} | {f['language']} | "
                      f"L:{f['lines']} C:{f['chars']} H:{f['short_hash']}\n")
        out.write(f"\n{SEPARATOR}\n\n")

        out.write("## PROJECT TREE (bundled files only)\n")
        for line in _render_tree([f["rel"] for f in files]):
            out.write(f"# {line}\n")
        out.write(f"\n{SEPARATOR}\n\n")

        out.write("## LANGUAGE BREAKDOWN\n")
        for lang in sorted(by_lang):
            out.write(f"# {lang}: {by_lang[lang]} file(s)\n")
        if secrets:
            out.write("#\n# SECRET FILES EXCLUDED (counted, never read):\n")
            for s in secrets:
                out.write(f"#   - {s}\n")
        if binary_skips:
            out.write(f"# Binary files skipped (unreadable as text): {binary_skips}\n")
        out.write(f"\n{SEPARATOR}\n\n")

        for i, f in enumerate(files, 1):
            out.write(f"# >>> FILE {i}/{len(files)}: {f['rel']} >>>\n")
            out.write(f"# language: {f['language']} | bytes_on_disk: {f['bytes']} | "
                      f"lines: {f['lines']} | chars: {f['chars']}\n")
            out.write(f"# sha256: {f['sha256']} | short_hash: {f['short_hash']}\n")
            out.write(f"# mtime_utc: {f['mtime_utc']}\n")
            if f["py"]:
                if f["py"]["docstring"]:
                    out.write(f"# module_doc: {f['py']['docstring']}\n")
                if f["py"]["imports"]:
                    out.write(f"# top_imports: {', '.join(f['py']['imports'])}\n")
                if f["py"]["defines"]:
                    out.write(f"# top_defs: {', '.join(f['py']['defines'])}\n")
            if f["notice"]:
                out.write(f"# NOTICE: {f['notice']}\n")
            out.write(f"{SUB_SEPARATOR}\n")
            out.write(f["content"])
            if f["content"] and not f["content"].endswith("\n"):
                out.write("\n")
            out.write(f"# <<< END FILE {i}/{len(files)}: {f['rel']} "
                      f"sha256={f['short_hash']} <<<\n")
            out.write(f"{SEPARATOR}\n\n")

        out.write("## MANIFEST (sha256 index — verify integrity / detect drift)\n")
        for f in files:
            out.write(f"# {f['short_hash']}  {f['rel']}\n")
        out.write(f"{SEPARATOR}\n")
        out.write(f"# SUMMARY | files={len(files)} lines={total_lines} chars={total_chars} "
                  f"generated={generated}\n")
        out.write(f"{SEPARATOR}\n")

    summary = {
        "output": output_file,
        "files": len(files),
        "lines": total_lines,
        "chars": total_chars,
        "by_language": by_lang,
        "secrets_excluded": secrets,
        "binaries_skipped": binary_skips,
    }
    print("[OK] Saved: full-trade.txt")
    print(f"[INFO] Files: {summary['files']} | Lines: {total_lines} | Chars: {total_chars}")
    print(f"[INFO] By language: {by_lang}")
    print(f"[INFO] Secrets excluded: {len(secrets)} | Binaries skipped: {binary_skips}")
    print(f"[INFO] Output: {output_file}")
    return summary


def save_all_project_code(root_path: str) -> dict:
    """Backward-compatible entry point kept for existing callers."""
    return build_bundle(root_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bundle source into one AI-reviewable file.")
    parser.add_argument("--root", default=None, help="Project root (default: parent of copyfile/).")
    parser.add_argument("--output", default=None, help="Output bundle path.")
    args = parser.parse_args(argv)
    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    build_bundle(root, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
