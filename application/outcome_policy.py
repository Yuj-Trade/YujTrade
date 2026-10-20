from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from domain.outcome import EVENT_KINDS

MODES = frozenset({"off", "shadow", "live"})


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class NotificationPolicy:
    mode: str
    kinds: frozenset[str]
    timeframes: frozenset[str]
    since: datetime | None
    max_attempts: int
    claim_ttl: timedelta
    watch_interval: timedelta
    concurrency: int

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


def build_policy(
    raw: Mapping[str, object], allowed_timeframes: frozenset[str]
) -> NotificationPolicy:
    mode = str(raw.get("outcome_notifications_mode", "off")).strip().lower()
    if mode not in MODES:
        raise PolicyError(f"unknown outcome_notifications_mode {mode!r}")
    return NotificationPolicy(
        mode=mode,
        kinds=_parse_kinds(raw.get("outcome_notification_kinds")),
        timeframes=_parse_timeframes(
            raw.get("outcome_notification_timeframes"), allowed_timeframes
        ),
        since=_parse_since(raw.get("outcome_notifications_since"), mode),
        max_attempts=_parse_positive_int(
            raw.get("outcome_notification_max_attempts"), "outcome_notification_max_attempts"
        ),
        claim_ttl=timedelta(
            seconds=_parse_positive_number(
                raw.get("outcome_claim_ttl_seconds"), "outcome_claim_ttl_seconds"
            )
        ),
        watch_interval=timedelta(
            minutes=_parse_positive_number(
                raw.get("outcome_watch_interval_minutes"), "outcome_watch_interval_minutes"
            )
        ),
        concurrency=_parse_positive_int(
            raw.get("outcome_watch_concurrency"), "outcome_watch_concurrency"
        ),
    )


def is_eligible(
    kind: str, timeframe: str, created_at: datetime, policy: NotificationPolicy
) -> bool:
    if kind not in policy.kinds:
        return False
    if timeframe not in policy.timeframes:
        return False
    if policy.since is None:
        return True
    moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    return moment.astimezone(UTC) >= policy.since


def failure_state(attempts: int, permanent: bool, max_attempts: int) -> str:
    if permanent or attempts >= max_attempts:
        return "abandoned"
    return "pending"


def _parse_since(raw_value: object, mode: str) -> datetime | None:
    if isinstance(raw_value, datetime):
        parsed = raw_value
    else:
        text = str(raw_value or "").strip()
        if not text:
            if mode != "off":
                raise PolicyError(
                    "outcome_notifications_since is required when the mode is not off"
                )
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise PolicyError(
                f"outcome_notifications_since is not an ISO timestamp: {text!r}"
            ) from exc
    if parsed.tzinfo is None:
        raise PolicyError("outcome_notifications_since must carry a timezone")
    return parsed.astimezone(UTC)


def _parse_kinds(raw_value: object) -> frozenset[str]:
    items = _as_sequence(raw_value, "outcome_notification_kinds")
    kinds = frozenset(str(item).strip().lower() for item in items)
    if not kinds:
        raise PolicyError("outcome_notification_kinds must not be empty")
    unsupported = kinds - EVENT_KINDS
    if unsupported:
        raise PolicyError(f"unsupported outcome notification kinds: {sorted(unsupported)}")
    return kinds


def _parse_timeframes(raw_value: object, allowed: frozenset[str]) -> frozenset[str]:
    items = _as_sequence(raw_value, "outcome_notification_timeframes")
    timeframes = frozenset(str(item).strip() for item in items)
    if not timeframes:
        return frozenset(allowed)
    unsupported = timeframes - allowed
    if unsupported:
        raise PolicyError(f"unsupported outcome notification timeframes: {sorted(unsupported)}")
    return timeframes


def _as_sequence(raw_value: object, name: str) -> tuple[object, ...]:
    if raw_value is None:
        raise PolicyError(f"{name} must be a list of strings")
    if isinstance(raw_value, str):
        return (raw_value,)
    if isinstance(raw_value, (list, tuple, set, frozenset)):
        return tuple(raw_value)
    raise PolicyError(f"{name} must be a list of strings")


def _parse_positive_int(raw_value: object, name: str) -> int:
    if isinstance(raw_value, bool) or raw_value is None:
        raise PolicyError(f"{name} must be a positive integer")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise PolicyError(f"{name} must be a positive integer")
    return value


def _parse_positive_number(raw_value: object, name: str) -> float:
    if isinstance(raw_value, bool) or raw_value is None:
        raise PolicyError(f"{name} must be a positive number")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{name} must be a positive number") from exc
    if not value > 0.0:
        raise PolicyError(f"{name} must be a positive number")
    return value
