import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load(script_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / script_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_report_contains_environment_fields():
    module = load("generate_reports.py", "generate_reports_env")
    report = module.build_report(ROOT)
    assert report["python"] == sys.version
    assert report["platform"]
    assert report["git_revision"]
    baseline = report["baseline"]
    assert Path(baseline["path"]) == Path("tests/golden/signals_baseline.json")
    assert baseline["sha256"] is not None
    assert baseline["items"] is not None and baseline["items"] > 0


def test_build_report_handles_missing_baseline(tmp_path):
    module = load("generate_reports.py", "generate_reports_missing")
    report = module.build_report(tmp_path)
    assert report["baseline"]["sha256"] is None
    assert report["baseline"]["items"] is None
    assert "generated_at_utc" in report


def test_main_writes_output_file(tmp_path, capsys):
    module = load("generate_reports.py", "generate_reports_main")
    out = tmp_path / "nested" / "baseline.json"
    sys.argv = ["generate_reports.py", "--output", str(out)]
    module.main()
    printed = capsys.readouterr().out.strip()
    assert printed == str(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["baseline"]["path"].endswith("signals_baseline.json")


def test_main_resolves_relative_output_under_root(capsys):
    module = load("generate_reports.py", "generate_reports_relative")
    sys.argv = ["generate_reports.py", "--output", "environment-relative.json"]
    try:
        module.main()
    finally:
        sys.argv = ["pytest"]
    capsys.readouterr()
    output = ROOT / "environment-relative.json"
    assert output.exists()
    output.unlink()


def test_git_revision_returns_string_or_none():
    module = load("generate_reports.py", "generate_reports_git")
    revision = module._git_revision()
    assert revision is None or (isinstance(revision, str) and len(revision) == 40)
