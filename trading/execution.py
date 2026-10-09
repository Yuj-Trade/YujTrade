import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
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


class ExchangeAdapter:
    def __init__(self, exchange: Any = None, dry_run: bool = True, fee_rate: float = 0.001):
        self.exchange = exchange
        self.dry_run = dry_run
        self.fee_rate = fee_rate

    async def fetch_price(self, symbol: str) -> Optional[float]:
        try:
            if self.exchange is None:
                return None
            ticker = await asyncio.to_thread(self.exchange.fetch_ticker, symbol)
            return float(ticker.get("last") or ticker.get("close") or 0.0) or None
        except Exception as e:
            logger.debug(f"Exchange price fetch failed for {symbol}: {e}")
            return None

    async def create_order(self, symbol: str, side: OrderSide, quantity: float, price: Optional[float] = None, order_type: OrderType = OrderType.MARKET) -> ExecutionResult:
        if self.dry_run or self.exchange is None:
            order_id = uuid.uuid4().hex[:12]
            return ExecutionResult(ok=True, order_id=order_id, price=float(price or 0.0), quantity=float(quantity), fee=float((price or 0.0) * quantity * self.fee_rate))
        try:
            side_str = "buy" if side == OrderSide.BUY else "sell"
            params = {"type": order_type.value}
            result = await asyncio.to_thread(self.exchange.create_order, symbol, params["type"], side_str, float(quantity), price)
            order_id = str(result.get("id", uuid.uuid4().hex[:12]))
            avg = float(result.get("average") or result.get("price") or price or 0.0)
            filled = float(result.get("filled") or result.get("amount") or quantity)
            fee = avg * filled * self.fee_rate
            return ExecutionResult(ok=True, order_id=order_id, price=avg, quantity=filled, fee=fee)
        except Exception as e:
            logger.error(f"Live order failed for {symbol}: {e}")
            return ExecutionResult(ok=False, error=str(e))


class FakeAdapter(ExchangeAdapter):
    def __init__(self, prices: Optional[Dict[str, float]] = None, fee_rate: float = 0.001):
        super().__init__(exchange=None, dry_run=True, fee_rate=fee_rate)
        self.prices = prices or {}

    async def fetch_price(self, symbol: str) -> Optional[float]:
        return self.prices.get(symbol)

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: Optional[float] = None,
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
    def __init__(self, adapter: Optional[ExchangeAdapter] = None, max_deviation_pct: float = 2.0, max_spread_pct: float = 0.5):
        self.adapter = adapter or ExchangeAdapter()
        self.max_deviation_pct = max_deviation_pct
        self.max_spread_pct = max_spread_pct
        self.orders: Dict[str, Order] = {}

    def _check_limit_price(self, market_price: float, limit_price: float) -> bool:
        if market_price <= 0:
            return False
        deviation = abs(limit_price - market_price) / market_price * 100.0
        return deviation <= self.max_deviation_pct

    async def execute(self, symbol: str, side: OrderSide, quantity: float, price: Optional[float] = None, order_type: OrderType = OrderType.MARKET, signal_id: Optional[str] = None, timeframe: Optional[str] = None) -> ExecutionResult:
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
        order = Order(
            order_id=result.order_id or uuid.uuid4().hex[:12],
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=float(quantity),
            price=float(exec_price),
            status=OrderStatus.FILLED if result.ok else OrderStatus.REJECTED,
            filled_quantity=float(result.quantity) if result.ok else 0.0,
            average_fill_price=float(result.price) if result.ok else 0.0,
            fee_paid=float(result.fee) if result.ok else 0.0,
            signal_id=signal_id,
            timeframe=timeframe,
            paper=self.adapter.dry_run,
            notes=result.error if not result.ok else "",
        )
        self.orders[order.order_id] = order
        return result
