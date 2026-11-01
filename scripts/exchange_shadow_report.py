import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

from config.logger import logger
from config.settings import ConfigManager
from trading.exchanges.gate_inputs import load_exchange_settings
from trading.live_ledger import LiveLedger


def _best_deviation(row: dict[str, Any]) -> float | None:
    reference = float(row.get("reference_price") or 0.0)
    if reference <= 0:
        return None
    intended = float(row.get("price") or 0.0)
    if intended <= 0:
        return None
    return abs(intended - reference) / reference * 100.0


def summarize_shadow_rows(
    rows: list[dict[str, Any]], refusals: dict[str, int] | None = None
) -> dict[str, Any]:
    reasons = Counter(str(row.get("reason") or "") for row in rows)
    for reason, count in (refusals or {}).items():
        reasons[str(reason)] += int(count)
    deviations = [value for value in (_best_deviation(row) for row in rows) if value is not None]
    exchanges = Counter(str(row.get("exchange_id") or "") for row in rows)
    mean_deviation = sum(deviations) / len(deviations) if deviations else 0.0
    max_deviation = max(deviations) if deviations else 0.0
    return {
        "count": len(rows),
        "reasons": dict(sorted(reasons.items())),
        "refusals": dict(sorted((refusals or {}).items())),
        "exchanges": dict(sorted(exchanges.items())),
        "mean_deviation_pct": round(mean_deviation, 6),
        "max_deviation_pct": round(max_deviation, 6),
        "deviation_samples": len(deviations),
        "rows_without_reference": sum(
            1 for row in rows if not float(row.get("reference_price") or 0)
        ),
    }


def format_report(summary: dict[str, Any]) -> str:
    lines = [f"Shadow rows: {summary['count']}"]
    lines.append(f"Mean deviation pct: {summary['mean_deviation_pct']}")
    lines.append(f"Max deviation pct: {summary['max_deviation_pct']}")
    lines.append(f"Deviation samples: {summary['deviation_samples']}")
    lines.append(f"Rows without a reference price: {summary['rows_without_reference']}")
    if summary["exchanges"]:
        lines.append("Exchanges:")
        for name, value in summary["exchanges"].items():
            lines.append(f"  {name}: {value}")
    if summary["reasons"]:
        lines.append("Reasons:")
        for name, value in summary["reasons"].items():
            lines.append(f"  {name or '(none)'}: {value}")
    return "\n".join(lines)


def soak_exit_criteria(summary: dict[str, Any], max_deviation_pct: float) -> dict[str, bool]:
    reasons = summary.get("reasons", {})
    return {
        "no_exchange_not_ready": int(reasons.get("exchange_not_ready", 0)) == 0,
        "no_key_not_attested": int(reasons.get("key_not_attested", 0)) == 0,
        "deviation_within_limit": float(summary.get("max_deviation_pct", 0.0)) <= max_deviation_pct,
        "has_samples": int(summary.get("deviation_samples", 0)) > 0,
    }


async def build_report(ledger: LiveLedger) -> dict[str, Any]:
    rows = await ledger.get_shadow_rows()
    refusals = await ledger.refusal_counts()
    return summarize_shadow_rows(rows, refusals)


async def run(output_path: Path) -> dict[str, Any]:
    settings = load_exchange_settings(ConfigManager())
    ledger = LiveLedger(settings.ledger_path)
    await ledger.initialize()
    summary = await build_report(ledger)
    summary["soak_exit"] = soak_exit_criteria(summary, settings.max_deviation_pct)
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
