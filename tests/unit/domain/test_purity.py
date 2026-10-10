import subprocess
import sys

FORBIDDEN = (
    "pandas",
    "numpy",
    "tensorflow",
    "xgboost",
    "backtrader",
    "telegram",
    "aiohttp",
    "sqlite3",
)


def test_domain_stays_stdlib_only():
    probe = (
        "import sys, domain.types, domain.levels, domain.gates,"
        " domain.outcome, domain.signal_id, domain.sizing;"
        " print(','.join(sorted(sys.modules)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    loaded = proc.stdout.strip().split(",")
    violations = [name for name in loaded if name.split(".")[0] in FORBIDDEN]
    assert violations == []
