import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.logger import logger
from config.settings import ConfigManager
from services.trading_service import build_performance_report_from_ledger
from trading.ledger import PaperLedger

DEFAULT_OUTPUT = Path("runs/performance/performance-report.json")


def _parse_as_of(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _build(as_of: datetime, ledger_path: Path) -> tuple[str, str]:
    config_manager = ConfigManager()
    ledger = PaperLedger(ledger_path)
    report = await build_performance_report_from_ledger(ledger, config_manager, as_of)
    return report.to_json(), report.data_hash


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the paper performance report")
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 instant the report is cut at, defaults to now (UTC)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="path of the JSON report",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("runs/paper_ledger.db"),
        help="path of the paper ledger",
    )
    args = parser.parse_args()
    as_of = _parse_as_of(args.as_of) if args.as_of else datetime.now(UTC)
    root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    payload, data_hash = asyncio.run(_build(as_of, args.ledger))
    output.write_text(payload, encoding="utf-8")
    logger.info(f"Performance report written to {output}")
    print(data_hash)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
