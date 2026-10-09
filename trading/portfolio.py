from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from common.core import Order, OrderStatus, Position, PositionSide


@dataclass
class PortfolioSnapshot:
    equity: float
    cash: float
    exposure_pct: float
    open_positions: int
    unrealized_pnl: float
    realized_pnl: float


class PortfolioManager:
    def __init__(self, initial_cash: float = 10000.0):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions: Dict[str, Position] = {}
        self.realized_pnl = 0.0
        self.orders: Dict[str, Order] = {}

    def equity(self, prices: Dict[str, float]) -> float:
        total = self.cash
        for position in self.positions.values():
            price = prices.get(position.symbol, position.entry_price)
            if position.side == PositionSide.LONG:
                total += position.quantity * price
            else:
                total += position.quantity * (2 * position.entry_price - price)
        return float(total)

    def exposure_pct(self, prices: Dict[str, float]) -> float:
        equity = self.equity(prices)
        if equity <= 0:
            return 0.0
        notional = 0.0
        for position in self.positions.values():
            price = prices.get(position.symbol, position.entry_price)
            notional += abs(position.quantity * price)
        return notional / equity * 100.0

    def unrealized_pnl(self, prices: Dict[str, float]) -> float:
        total = 0.0
        for position in self.positions.values():
            price = prices.get(position.symbol, position.entry_price)
            if position.side == PositionSide.LONG:
                total += (price - position.entry_price) * position.quantity
            else:
                total += (position.entry_price - price) * position.quantity
        return float(total)

    def open_position(self, position: Position, cost: float, fee: float = 0.0):
        self.positions[position.position_id] = position
        self.cash -= cost + fee
        self.realized_pnl -= fee

    def close_position(self, position_id: str, exit_price: float, fee: float = 0.0) -> float:
        position = self.positions.pop(position_id)
        if position.side == PositionSide.LONG:
            proceeds = position.quantity * exit_price
            pnl = (exit_price - position.entry_price) * position.quantity
        else:
            proceeds = position.quantity * (2 * position.entry_price - exit_price)
            pnl = (position.entry_price - exit_price) * position.quantity
        self.cash += proceeds - fee
        self.realized_pnl += pnl - fee
        return float(pnl - fee)

    def portfolio_heat(self, prices: Dict[str, float]) -> float:
        equity = self.equity(prices)
        if equity <= 0:
            return 0.0
        total_risk = sum(getattr(p, "risk_amount", 0.0) or 0.0 for p in self.positions.values())
        return total_risk / equity * 100.0

    def snapshot(self, prices: Dict[str, float]) -> PortfolioSnapshot:
        equity = self.equity(prices)
        return PortfolioSnapshot(
            equity=equity,
            cash=self.cash,
            exposure_pct=self.exposure_pct(prices),
            open_positions=len(self.positions),
            unrealized_pnl=self.unrealized_pnl(prices),
            realized_pnl=self.realized_pnl,
        )

    def positions_by_symbol(self, symbol: str) -> List[Position]:
        return [p for p in self.positions.values() if p.symbol == symbol]
