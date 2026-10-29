import hmac
import secrets
from datetime import UTC, datetime, timedelta

from trading.live_ledger import LiveLedger

_PREFIX = "confirm:"
_DEFAULT_TTL_SECONDS = 60.0


def _now() -> datetime:
    return datetime.now(UTC)


def _key(code: str) -> str:
    return f"{_PREFIX}{code}"


async def issue_confirmation(
    ledger: LiveLedger,
    exchange_id: str,
    signal_id: str,
    ttl_seconds: float = _DEFAULT_TTL_SECONDS,
) -> str:
    code = secrets.token_hex(4).upper()
    expires_at = (_now() + timedelta(seconds=ttl_seconds)).isoformat()
    await ledger.set_control(_key(code), f"{exchange_id}|{signal_id}|{expires_at}|pending")
    return code


async def consume_confirmation(
    ledger: LiveLedger,
    code: str,
    exchange_id: str,
    signal_id: str,
    now: datetime | None = None,
) -> tuple[bool, str]:
    if not code:
        return False, "confirmation_missing"
    stored = await ledger.get_control(_key(code), "")
    if not stored:
        return False, "confirmation_unknown"
    parts = stored.split("|")
    if len(parts) != 4:
        return False, "confirmation_unknown"
    stored_exchange, stored_signal, expires_at, state = parts
    if state != "pending":
        return False, "confirmation_already_used"
    if not hmac.compare_digest(stored_exchange, exchange_id) or not hmac.compare_digest(
        stored_signal, signal_id
    ):
        return False, "confirmation_mismatch"
    moment = now or _now()
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False, "confirmation_unknown"
    if moment > expiry:
        await ledger.set_control(
            _key(code), f"{stored_exchange}|{stored_signal}|{expires_at}|expired"
        )
        return False, "confirmation_expired"
    await ledger.set_control(_key(code), f"{stored_exchange}|{stored_signal}|{expires_at}|used")
    return True, "ok"
