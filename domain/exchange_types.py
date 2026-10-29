from dataclasses import dataclass

PENDING_SUBMIT = "pending_submit"
SUBMITTED = "submitted"
OPEN = "open"
PARTIALLY_FILLED = "partially_filled"
FILLED = "filled"
CANCELED = "canceled"
REJECTED = "rejected"
EXPIRED = "expired"
UNKNOWN = "unknown"
SHADOW = "shadow"

TERMINAL_STATUSES = frozenset({FILLED, CANCELED, REJECTED, EXPIRED, SHADOW})
NON_TERMINAL_STATUSES = frozenset({PENDING_SUBMIT, SUBMITTED, OPEN, PARTIALLY_FILLED, UNKNOWN})


@dataclass(frozen=True)
class OrderIntent:
    exchange_id: str
    signal_id: str
    symbol: str
    side: str
    amount: float
    price: float
    client_order_id: str
    sandbox: bool


@dataclass(frozen=True)
class PlacementResult:
    accepted: bool
    exchange_order_id: str = ""
    error: str = ""
    fee_cost: float = 0.0
    fee_currency: str = ""


@dataclass(frozen=True)
class OrderSnapshot:
    exchange_order_id: str
    client_order_id: str
    status: str
    filled: float
    average_price: float
    fee_cost: float
    fee_currency: str
