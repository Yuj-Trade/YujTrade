from dataclasses import dataclass
from datetime import datetime

from application.outcome_message import render_outcome
from application.outcome_policy import NotificationPolicy, failure_state, is_eligible
from application.outcome_ports import NotificationDeliveryError, OutcomeNotifier
from common import metrics
from config.logger import logger
from strategy.signal_tracker import SignalTracker


@dataclass(frozen=True)
class DispatchReport:
    sent: int
    shadowed: int
    suppressed: int
    retried: int
    abandoned: int


async def dispatch_outcomes(
    tracker: SignalTracker,
    notifier: OutcomeNotifier | None,
    policy: NotificationPolicy,
    now: datetime,
) -> DispatchReport:
    sent = 0
    shadowed = 0
    suppressed = 0
    retried = 0
    abandoned = 0

    for pending in await tracker.due_notifications():
        if not is_eligible(pending.event.kind, pending.timeframe, pending.created_at, policy):
            await tracker.complete_notification(pending.signal_id, "suppressed")
            suppressed += 1
            metrics.record_outcome_notification("suppressed")
            continue
        if policy.mode == "shadow":
            logger.info(
                f"Outcome shadow for {pending.signal_id}: {pending.event.kind} at "
                f"{pending.event.price}"
            )
            await tracker.complete_notification(pending.signal_id, "shadowed")
            shadowed += 1
            metrics.record_outcome_notification("shadowed")
            continue
        if notifier is None:
            logger.warning(f"Outcome notification for {pending.signal_id} has no delivery channel.")
            continue
        if not await tracker.claim_notification(pending.signal_id, now, policy.claim_ttl):
            continue
        text = render_outcome(
            pending.symbol, pending.timeframe, pending.side, pending.entry, pending.event
        )
        try:
            await notifier.send(text)
        except NotificationDeliveryError as exc:
            state = failure_state(pending.attempts + 1, exc.permanent, policy.max_attempts)
            await tracker.fail_notification(pending.signal_id, state)
            if state == "abandoned":
                abandoned += 1
            else:
                retried += 1
            metrics.record_outcome_notification(state)
            continue
        except Exception as exc:
            logger.error(f"Outcome notification for {pending.signal_id} failed unexpectedly: {exc}")
            state = failure_state(pending.attempts + 1, False, policy.max_attempts)
            await tracker.fail_notification(pending.signal_id, state)
            if state == "abandoned":
                abandoned += 1
            else:
                retried += 1
            metrics.record_outcome_notification(state)
            continue
        await tracker.complete_notification(pending.signal_id, "sent")
        sent += 1
        metrics.record_outcome_notification("sent")

    return DispatchReport(sent, shadowed, suppressed, retried, abandoned)
