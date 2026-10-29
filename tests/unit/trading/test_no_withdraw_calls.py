import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXCHANGE_DIR = ROOT / "trading" / "exchanges"

FORBIDDEN = re.compile(
    r"\b(withdraw|transfer|create_deposit_address|fetch_deposit_address|"
    r"fetch_deposit_addresses)\b"
)


def _exchange_modules() -> list[Path]:
    return sorted(EXCHANGE_DIR.glob("*.py"))


def test_exchange_package_exists_and_is_scanned():
    assert _exchange_modules()


def test_no_withdrawal_or_transfer_calls_in_exchange_package():
    offenders = []
    for path in _exchange_modules():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
