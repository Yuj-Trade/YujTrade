from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from application.exchange_policy import next_status
from common import metrics
from config.logger import logger
from domain.exchange_types import PENDING_SUBMIT, UNKNOWN
from trading.live_ledger import LiveLedger

AdminNotice = Callable[[str], Awaitable[None]]


def _age_seconds(created_at: str, now_utc: datetime) -> float:
    try:
        created = datetime.fromisoformat(str(created_at))
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (now_utc - created).total_seconds()


async def reconcile_once(
    ledger: LiveLedger,
    gateways_by_exchange: dict[str, Any],
    unknown_after_seconds: float,
    now_utc: datetime | None = None,
    notify: AdminNotice | None = None,
) -> list[str]:
    moment = now_utc or datetime.now(UTC)
    changed: list[str] = []
    for row in await ledger.get_non_terminal():
        exchange_id = str(row["exchange_id"])
        gateway = gateways_by_exchange.get(exchange_id)
        if gateway is None:
            logger.warning(f"Reconciliation has no gateway for {exchange_id}")
            continue
        snapshot = None
        try:
            snapshot = await gateway.fetch_order_by_client_id(
                str(row["symbol"]), str(row["client_order_id"])
            )
        except Exception as exc:
            text = gateway.error_text(exc) if hasattr(gateway, "error_text") else str(exc)
            logger.error(f"Reconciliation read failed for {exchange_id}: {text}")
            continue
        observed = snapshot.status if snapshot is not None else None
        target = next_status(
            str(row["status"]),
            observed,
            _age_seconds(row["created_at_utc"], moment),
            unknown_after_seconds,
        )
        if target == row["status"]:
            continue
        if snapshot is not None:
            await ledger.update_from_snapshot(str(row["client_order_id"]), exchange_id, snapshot)
        else:
            await ledger.set_status(
                str(row["client_order_id"]), exchange_id, target, "reconcile_no_snapshot"
            )
        changed.append(str(row["client_order_id"]))
        if target == UNKNOWN:
            metrics.record_exchange_unknown(exchange_id)
        if target == UNKNOWN and notify is not None:
            await notify(
                f"Order {row['client_order_id']} on {exchange_id} is unknown; "
                "manual review required"
            )
        if row["status"] == PENDING_SUBMIT and target == UNKNOWN:
            logger.warning(
                f"Pending submission {row['client_order_id']} on {exchange_id} is unknown."
            )
    return changed
