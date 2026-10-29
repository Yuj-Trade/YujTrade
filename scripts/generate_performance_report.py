import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.performance_report import build_portfolio_summary
from config.logger import logger
from config.settings import ConfigManager
from domain.performance import ClosedTrade
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
    payload = json.loads(report.to_json())
    portfolio = await _paper_portfolio(ledger, config_manager, as_of)
    if portfolio is not None:
        payload["paper_portfolio"] = portfolio
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return text, report.data_hash


async def _paper_portfolio(
    ledger: PaperLedger, config_manager: ConfigManager, as_of: datetime
) -> dict[str, object] | None:
    rows = await ledger.load_closed_positions()
    if not rows:
        return None
    defaults = ConfigManager.DEFAULT_CONFIG
    closed = [
        ClosedTrade(row["exit_at_utc"], row["position_id"], row["return_fraction"])
        for row in rows
        if row["exit_at_utc"].date() <= as_of.date()
    ]
    if not closed:
        return None
    return build_portfolio_summary(
        closed,
        float(config_manager.get("initial_cash", defaults["initial_cash"])),
        start=min(item.exit_at.date() for item in closed),
        end=as_of.date(),
        periods_per_year=float(
            config_manager.get(
                "performance_periods_per_year", defaults["performance_periods_per_year"]
            )
        ),
        rf_annual=float(
            config_manager.get("performance_rf_annual", defaults["performance_rf_annual"])
        ),
        min_trades_for_ratios=int(
            config_manager.get(
                "performance_min_trades_for_ratios", defaults["performance_min_trades_for_ratios"]
            )
        ),
    )


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
