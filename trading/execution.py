import uuid
from dataclasses import dataclass
from typing import Any

from common.core import Order, OrderSide, OrderStatus, OrderType
from config.logger import logger


@dataclass
class ExecutionResult:
    ok: bool
    order_id: str = ""
    price: float = 0.0
    quantity: float = 0.0
    fee: float = 0.0
    error: str = ""
    status: str = ""


_LIMIT_OPEN_STATUSES = {"open", "new", "pending", "partially_filled", "partial", "created"}


class ExchangeAdapter:
    def __init__(self, exchange: Any = None, dry_run: bool = True, fee_rate: float = 0.001):
        self.exchange = exchange
        self.dry_run = dry_run
        self.fee_rate = fee_rate

    async def fetch_price(self, symbol: str) -> float | None:
        try:
            if self.exchange is None:
                return None
            ticker = await self.exchange.fetch_ticker(symbol)
            return float(ticker.get("last") or ticker.get("close") or 0.0) or None
        except Exception as e:
            logger.debug(f"Exchange price fetch failed for {symbol}: {e}")
            return None

    @staticmethod
    def _resolution_status(result: dict[str, Any], order_type: OrderType) -> OrderStatus:
        raw = str(result.get("status") or "").strip().lower()
        if raw == "closed" or raw == "filled":
            return OrderStatus.FILLED
        if raw in {"canceled", "cancelled"}:
            return OrderStatus.CANCELLED
        if raw == "expired":
            return OrderStatus.EXPIRED
        if raw == "rejected":
            return OrderStatus.REJECTED
        if order_type == OrderType.LIMIT:
            return OrderStatus.OPEN
        if raw in _LIMIT_OPEN_STATUSES:
            return OrderStatus.OPEN
        return OrderStatus.PENDING

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float | None = None,
        order_type: OrderType = OrderType.MARKET,
    ) -> ExecutionResult:
        if self.dry_run:
            order_id = uuid.uuid4().hex[:12]
            return ExecutionResult(
                ok=True,
                order_id=order_id,
                price=float(price or 0.0),
                quantity=float(quantity),
                fee=float((price or 0.0) * quantity * self.fee_rate),
            )
        if self.exchange is None:
            return ExecutionResult(ok=False, error="exchange_not_configured")
        try:
            side_str = "buy" if side == OrderSide.BUY else "sell"
            result = await self.exchange.create_order(
                symbol, order_type.value, side_str, float(quantity), price
            )
        except Exception as e:
            logger.error(f"Live order failed for {symbol}: {e}")
            return ExecutionResult(ok=False, error=str(e))
        if not isinstance(result, dict):
            return ExecutionResult(ok=False, error="missing_order_id")
        order_id = str(result.get("id") or "").strip()
        if not order_id:
            return ExecutionResult(ok=False, error="missing_order_id")
        if result.get("filled") is None:
            return ExecutionResult(ok=False, order_id=order_id, error="fill_unknown")
        filled = float(result.get("filled") or 0.0)
        average = float(result.get("average") or result.get("price") or price or 0.0)
        fee_payload = result.get("fee") or {}
        fee_cost = result.get("fee_cost")
        if fee_cost is None and isinstance(fee_payload, dict):
            fee_cost = fee_payload.get("cost")
        if fee_cost is None:
            return ExecutionResult(
                ok=False, order_id=order_id, error="fee_unknown", quantity=filled, price=average
            )
        return ExecutionResult(
            ok=True,
            order_id=order_id,
            price=average,
            quantity=filled,
            fee=float(fee_cost),
            status=str(result.get("status") or ""),
        )

    def resolve_status(self, result: ExecutionResult, order_type: OrderType) -> OrderStatus:
        if not result.ok:
            return OrderStatus.REJECTED
        return self._resolution_status({"status": result.status}, order_type)


class FakeAdapter(ExchangeAdapter):
    def __init__(self, prices: dict[str, float] | None = None, fee_rate: float = 0.001):
        super().__init__(exchange=None, dry_run=True, fee_rate=fee_rate)
        self.prices = prices or {}

    async def fetch_price(self, symbol: str) -> float | None:
        return self.prices.get(symbol)

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float | None = None,
        order_type: OrderType = OrderType.MARKET,
    ) -> ExecutionResult:
        fill_price = price if price is not None else self.prices.get(symbol)
        if fill_price is None:
            return ExecutionResult(ok=False, error="no_fake_price")
        return ExecutionResult(
            ok=True,
            order_id=f"fake-{uuid.uuid4().hex[:12]}",
            price=float(fill_price),
            quantity=float(quantity),
            fee=float(fill_price * quantity * self.fee_rate),
        )


class ExecutionEngine:
    def __init__(
        self,
        adapter: ExchangeAdapter | None = None,
        max_deviation_pct: float = 2.0,
        max_spread_pct: float = 0.5,
    ):
        self.adapter = adapter or ExchangeAdapter()
        self.max_deviation_pct = max_deviation_pct
        self.max_spread_pct = max_spread_pct
        self.orders: dict[str, Order] = {}

    def _check_limit_price(self, market_price: float, limit_price: float) -> bool:
        if market_price <= 0:
            return False
        deviation = abs(limit_price - market_price) / market_price * 100.0
        return deviation <= self.max_deviation_pct

    async def execute(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float | None = None,
        order_type: OrderType = OrderType.MARKET,
        signal_id: str | None = None,
        timeframe: str | None = None,
    ) -> ExecutionResult:
        if quantity <= 0:
            return ExecutionResult(ok=False, error="invalid_quantity")
        market_price = await self.adapter.fetch_price(symbol)
        if order_type == OrderType.LIMIT and price is not None and market_price:
            if not self._check_limit_price(market_price, price):
                return ExecutionResult(ok=False, error="limit_price_deviation")
        exec_price = price if price is not None else (market_price or 0.0)
        if exec_price <= 0:
            return ExecutionResult(ok=False, error="no_price")
        result = await self.adapter.create_order(symbol, side, quantity, exec_price, order_type)
        if not result.ok and not result.order_id:
            return result
        status = self.adapter.resolve_status(result, order_type)
        self.orders[result.order_id] = Order(
            order_id=result.order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=float(quantity),
            price=float(exec_price),
            status=status,
            filled_quantity=float(result.quantity) if result.ok else 0.0,
            average_fill_price=float(result.price) if result.ok else 0.0,
            fee_paid=float(result.fee) if result.ok else 0.0,
            signal_id=signal_id,
            timeframe=timeframe,
            paper=self.adapter.dry_run,
            notes=result.error if not result.ok else "",
        )
        return result
