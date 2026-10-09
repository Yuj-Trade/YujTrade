import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from common.core import Order, OrderSide, OrderStatus, OrderType, Position, PositionSide, RiskDecision, SignalType, TradingSignal
from trading.portfolio import PortfolioManager
from trading.risk_manager import RiskManager


class PaperTradingEngine:
    def __init__(self, portfolio: Optional[PortfolioManager] = None, risk_manager: Optional[RiskManager] = None, fee_rate: float = 0.001, slippage_rate: float = 0.0005, funding_rate_per_day: float = 0.0):
        self.portfolio = portfolio or PortfolioManager()
        self.risk_manager = risk_manager or RiskManager()
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.funding_rate_per_day = funding_rate_per_day
        self.orders: Dict[str, Order] = {}
        self.trade_history: List[Dict] = []

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        if side == OrderSide.BUY:
            return price * (1 + self.slippage_rate)
        return price * (1 - self.slippage_rate)

    def submit_signal(self, signal: TradingSignal, equity: float, prices: Dict[str, float], current_vol_pct: float = 0.0) -> Optional[Order]:
        exposure = self.portfolio.exposure_pct(prices)
        decision = self.risk_manager.evaluate(signal, equity, exposure, len(self.portfolio.positions), current_vol_pct)
        if not decision.allowed or decision.position_size <= 0:
            return None
        side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL
        return self.create_order(signal.symbol, side, decision.position_size, signal.entry_price, signal_id=getattr(signal, "signal_id", None), timeframe=signal.timeframe)

    def create_order(self, symbol: str, side: OrderSide, quantity: float, price: float, order_type: OrderType = OrderType.MARKET, signal_id: Optional[str] = None, timeframe: Optional[str] = None) -> Order:
        order = Order(
            order_id=uuid.uuid4().hex[:12],
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=float(quantity),
            price=float(price),
            status=OrderStatus.OPEN,
            signal_id=signal_id,
            timeframe=timeframe,
            paper=True,
        )
        self.orders[order.order_id] = order
        self.portfolio.orders[order.order_id] = order
        return order

    def fill_order(self, order_id: str, market_price: float, stop_loss: float = 0.0, take_profit: float = 0.0) -> Optional[Position]:
        order = self.orders.get(order_id)
        if order is None or order.status not in (OrderStatus.OPEN, OrderStatus.PENDING, OrderStatus.PARTIAL):
            return None
        fill_price = self._apply_slippage(market_price, order.side)
        fee = fill_price * order.quantity * self.fee_rate
        order.filled_quantity = order.quantity
        order.average_fill_price = fill_price
        order.fee_paid = fee
        order.status = OrderStatus.FILLED
        order.updated_at = datetime.now(timezone.utc)
        side = PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT
        position = Position(
            position_id=uuid.uuid4().hex[:12],
            symbol=order.symbol,
            side=side,
            quantity=order.quantity,
            entry_price=fill_price,
            stop_loss=float(stop_loss or fill_price * 0.98),
            take_profit=float(take_profit or fill_price * 1.04),
            signal_id=order.signal_id,
            timeframe=order.timeframe,
            risk_amount=abs(fill_price - stop_loss) * order.quantity if stop_loss else 0.0,
            fees_paid=fee,
        )
        cost = order.quantity * fill_price if side == PositionSide.LONG else 0.0
        self.portfolio.open_position(position, cost, fee if side == PositionSide.LONG else fee)
        self.trade_history.append({"order_id": order.order_id, "position_id": position.position_id, "symbol": order.symbol, "side": side.value, "price": fill_price, "quantity": order.quantity})
        return position

    def apply_funding(self, prices: Dict[str, float], days: float = 1.0) -> float:
        total = 0.0
        for position in self.portfolio.positions.values():
            price = prices.get(position.symbol, position.entry_price)
            funding = price * position.quantity * self.funding_rate_per_day * days
            total += funding
            self.portfolio.cash -= funding
            self.portfolio.realized_pnl -= funding
        return total

    def update_positions(self, prices: Dict[str, float]) -> List[Dict]:
        closed: List[Dict] = []
        for position_id, position in list(self.portfolio.positions.items()):
            price = prices.get(position.symbol)
            if price is None:
                continue
            hit_stop = price <= position.stop_loss if position.side == PositionSide.LONG else price >= position.stop_loss
            hit_target = price >= position.take_profit if position.side == PositionSide.LONG else price <= position.take_profit
            if hit_stop or hit_target:
                exit_price = position.stop_loss if hit_stop else position.take_profit
                fee = exit_price * position.quantity * self.fee_rate
                pnl = self.portfolio.close_position(position_id, exit_price, fee)
                closed.append({"position_id": position_id, "symbol": position.symbol, "exit": exit_price, "pnl": pnl, "reason": "stop" if hit_stop else "target"})
        return closed

    def cancel_order(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status not in (OrderStatus.OPEN, OrderStatus.PENDING):
            return False
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        return True
