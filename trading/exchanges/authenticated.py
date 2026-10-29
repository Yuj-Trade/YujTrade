from datetime import UTC, datetime, timedelta
from typing import Any

from application.exchange_policy import map_ccxt_status
from domain.exchange_types import OrderSnapshot
from trading.exchanges.ccxt_gateway import CcxtGateway
from trading.exchanges.errors import ExchangeConfigError

_CLOSED_ORDER_WINDOW = timedelta(hours=24)


class AuthenticatedQueries:
    def __init__(self, gateway: CcxtGateway) -> None:
        self.gateway = gateway

    async def fetch_free_balance(self, currency: str) -> float:
        balance = await self.gateway.client.fetch_balance()
        free = (balance or {}).get("free") or {}
        value = free.get(currency)
        if value is None:
            return 0.0
        return float(value)

    async def fetch_order_by_client_id(
        self, symbol: str, client_order_id: str
    ) -> OrderSnapshot | None:
        gateway = self.gateway
        gateway._market(symbol)
        since = int((datetime.now(UTC) - _CLOSED_ORDER_WINDOW).timestamp() * 1000)
        open_orders = await gateway.client.fetch_open_orders(symbol)
        closed_orders = await gateway.client.fetch_closed_orders(symbol, since=since)
        matches = [
            order
            for order in list(open_orders or []) + list(closed_orders or [])
            if str(order.get("clientOrderId") or "") == client_order_id
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise ExchangeConfigError("duplicate_client_order_id")
        order = matches[0]
        amount = float(order.get("amount") or 0.0)
        filled = float(order.get("filled") or 0.0)
        fee = order.get("fee") or {}
        fee_cost = float(fee.get("cost") or 0.0) if isinstance(fee, dict) else 0.0
        fee_currency = str(fee.get("currency") or "") if isinstance(fee, dict) else ""
        return OrderSnapshot(
            exchange_order_id=str(order.get("id") or ""),
            client_order_id=client_order_id,
            status=map_ccxt_status(order.get("status"), filled, amount),
            filled=filled,
            average_price=float(order.get("average") or order.get("price") or 0.0),
            fee_cost=fee_cost,
            fee_currency=fee_currency,
        )


async def fetch_trading_fee(gateway: CcxtGateway, symbol: str) -> dict[str, Any]:
    if not gateway.has("fetchTradingFee"):
        raise ExchangeConfigError("fetch_trading_fee_not_supported")
    fee = await gateway.client.fetch_trading_fee(symbol)
    return fee if isinstance(fee, dict) else {}
