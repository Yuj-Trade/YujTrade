import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from common.core import Order, OrderSide, OrderStatus, OrderType, PositionSide


@dataclass
class BracketOrder:
    entry: Order
    stop: Order
    target: Order
    position_id: Optional[str] = None


class OrderManager:
    def __init__(self) -> None:
        self.orders: Dict[str, Order] = {}
        self.trailing: Dict[str, float] = {}

    def bracket(self, symbol: str, side: OrderSide, quantity: float, entry: float, stop: float, target: float, signal_id: Optional[str] = None, timeframe: Optional[str] = None) -> BracketOrder:
        entry_o = Order(order_id=uuid.uuid4().hex[:12], symbol=symbol, side=side, order_type=OrderType.LIMIT, quantity=float(quantity), price=float(entry), status=OrderStatus.OPEN, signal_id=signal_id, timeframe=timeframe, paper=True)
        stop_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        stop_o = Order(order_id=uuid.uuid4().hex[:12], symbol=symbol, side=stop_side, order_type=OrderType.STOP, quantity=float(quantity), stop_price=float(stop), status=OrderStatus.OPEN, signal_id=signal_id, timeframe=timeframe, paper=True)
        target_o = Order(order_id=uuid.uuid4().hex[:12], symbol=symbol, side=stop_side, order_type=OrderType.LIMIT, quantity=float(quantity), price=float(target), status=OrderStatus.OPEN, signal_id=signal_id, timeframe=timeframe, paper=True)
        for o in (entry_o, stop_o, target_o):
            self.orders[o.order_id] = o
        return BracketOrder(entry=entry_o, stop=stop_o, target=target_o)

    def set_trailing(self, position_id: str, distance_pct: float) -> None:
        self.trailing[position_id] = float(distance_pct)

    def update_trailing(self, position_id: str, side: PositionSide, current_price: float, stop_price: float, highest: float = 0.0, lowest: float = 0.0) -> float:
        dist = self.trailing.get(position_id, 0.0)
        if dist <= 0 or current_price <= 0:
            return stop_price
        if side == PositionSide.LONG:
            ref = max(highest, current_price)
            candidate = ref * (1 - dist / 100.0)
            return max(stop_price, candidate)
        ref = min(lowest or current_price, current_price)
        candidate = ref * (1 + dist / 100.0)
        return min(stop_price, candidate) if stop_price else candidate

    def cancel_bracket(self, bracket: BracketOrder) -> None:
        for o in (bracket.entry, bracket.stop, bracket.target):
            if o.status in (OrderStatus.OPEN, OrderStatus.PENDING):
                o.status = OrderStatus.CANCELLED
                o.updated_at = datetime.now(timezone.utc)

    def open_orders(self) -> List[Order]:
        return [o for o in self.orders.values() if o.status in (OrderStatus.OPEN, OrderStatus.PENDING, OrderStatus.PARTIAL)]
