import hmac
import secrets
from datetime import UTC, datetime, timedelta

from trading.live_ledger import LiveLedger

_PREFIX = "confirm:"
_DEFAULT_TTL_SECONDS = 60.0
_PENDING = "pending"
_USED = "used"
_EXPIRED = "expired"


def _now() -> datetime:
    return datetime.now(UTC)


def _key(code: str) -> str:
    return f"{_PREFIX}{code}"


def _encode(exchange_id: str, signal_id: str, expires_at: str, state: str) -> str:
    return f"{exchange_id}|{signal_id}|{expires_at}|{state}"


def _decode(stored: str) -> tuple[str, str, str, str] | None:
    parts = stored.split("|")
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]


async def issue_confirmation(
    ledger: LiveLedger,
    exchange_id: str,
    signal_id: str,
    ttl_seconds: float = _DEFAULT_TTL_SECONDS,
) -> str:
    code = secrets.token_hex(4).upper()
    expires_at = (_now() + timedelta(seconds=ttl_seconds)).isoformat()
    await ledger.set_control(_key(code), _encode(exchange_id, signal_id, expires_at, _PENDING))
    return code


async def check_confirmation(
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
    decoded = _decode(stored)
    if decoded is None:
        return False, "confirmation_unknown"
    stored_exchange, stored_signal, expires_at, state = decoded
    if state != _PENDING:
        return False, "confirmation_already_used"
    if not hmac.compare_digest(stored_exchange, exchange_id) or not hmac.compare_digest(
        stored_signal, signal_id
    ):
        return False, "confirmation_mismatch"
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return False, "confirmation_unknown"
    if (now or _now()) > expiry:
        return False, "confirmation_expired"
    return True, "ok"


async def consume_confirmation(
    ledger: LiveLedger,
    code: str,
    exchange_id: str,
    signal_id: str,
    now: datetime | None = None,
) -> tuple[bool, str]:
    allowed, reason = await check_confirmation(ledger, code, exchange_id, signal_id, now)
    if not allowed:
        if reason == "confirmation_expired":
            stored = await ledger.get_control(_key(code), "")
            decoded = _decode(stored) if stored else None
            if decoded is not None:
                await ledger.set_control(
                    _key(code),
                    _encode(decoded[0], decoded[1], decoded[2], _EXPIRED),
                )
        return allowed, reason
    stored = await ledger.get_control(_key(code), "")
    decoded = _decode(stored)
    if decoded is None:
        return False, "confirmation_unknown"
    pending = _encode(decoded[0], decoded[1], decoded[2], _PENDING)
    used = _encode(decoded[0], decoded[1], decoded[2], _USED)
    flipped = await ledger.compare_and_set_control(_key(code), pending, used)
    if not flipped:
        return False, "confirmation_already_used"
    return True, "ok"
