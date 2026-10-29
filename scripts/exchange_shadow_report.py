import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

from config.logger import logger
from config.settings import ConfigManager
from trading.exchanges.gate_inputs import load_exchange_settings
from trading.live_ledger import LiveLedger


def summarize_shadow_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = Counter(str(row.get("reason") or "") for row in rows)
    deviations = []
    for row in rows:
        price = float(row.get("price") or 0.0)
        average = float(row.get("average_price") or 0.0)
        if price > 0 and average > 0:
            deviations.append(abs(average - price) / price * 100.0)
    exchanges = Counter(str(row.get("exchange_id") or "") for row in rows)
    mean_deviation = sum(deviations) / len(deviations) if deviations else 0.0
    return {
        "count": len(rows),
        "reasons": dict(sorted(reasons.items())),
        "exchanges": dict(sorted(exchanges.items())),
        "mean_deviation_pct": round(mean_deviation, 6),
        "deviation_samples": len(deviations),
    }


def format_report(summary: dict[str, Any]) -> str:
    lines = [f"Shadow rows: {summary['count']}"]
    lines.append(f"Mean deviation pct: {summary['mean_deviation_pct']}")
    lines.append(f"Deviation samples: {summary['deviation_samples']}")
    if summary["exchanges"]:
        lines.append("Exchanges:")
        for name, value in summary["exchanges"].items():
            lines.append(f"  {name}: {value}")
    if summary["reasons"]:
        lines.append("Reasons:")
        for name, value in summary["reasons"].items():
            lines.append(f"  {name or '(none)'}: {value}")
    return "\n".join(lines)


async def build_report(ledger: LiveLedger) -> dict[str, Any]:
    rows = await ledger.get_shadow_rows()
    return summarize_shadow_rows(rows)


async def run(output_path: Path) -> dict[str, Any]:
    settings = load_exchange_settings(ConfigManager())
    ledger = LiveLedger(settings.ledger_path)
    await ledger.initialize()
    summary = await build_report(ledger)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    summary = asyncio.run(run(Path("runs/exchange_shadow_report.json")))
    logger.info("Shadow report:\n" + format_report(summary))


if __name__ == "__main__":
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
