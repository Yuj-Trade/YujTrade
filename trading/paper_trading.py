import uuid
from datetime import UTC, datetime

from common.constants import SIGNAL_EXPIRY_BY_TIMEFRAME, candle_duration
from common.core import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    SignalType,
    TradingSignal,
)
from config.logger import logger
from domain.costs import CostProfile, fee_rate, fill_fraction, legacy_report_profile
from domain.outcome import resolve_signal_outcome
from trading.portfolio import PortfolioManager
from trading.risk_manager import RiskManager


class PaperTradingEngine:
    def __init__(
        self,
        portfolio: PortfolioManager | None = None,
        risk_manager: RiskManager | None = None,
        *,
        fee_rate: float,
        slippage_rate: float,
        cost_profile: CostProfile | None = None,
    ):
        self.portfolio = portfolio or PortfolioManager()
        self.risk_manager = risk_manager or RiskManager()
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.cost_profile = cost_profile or legacy_report_profile(fee_rate, slippage_rate)
        self.orders: dict[str, Order] = {}
        self.trade_history: list[dict] = []

    def _legacy_profile(self) -> bool:
        return self.cost_profile.version == "legacy-report-v1"

    def _entry_price(self, market_price: float, side: OrderSide) -> float:
        profile = self.cost_profile
        if profile.entry_liquidity != "taker":
            return market_price
        if side == OrderSide.BUY:
            return market_price * (1 + profile.entry_slippage_rate)
        return market_price * (1 - profile.entry_slippage_rate)

    def submit_signal(
        self,
        signal: TradingSignal,
        equity: float,
        prices: dict[str, float],
        current_vol_pct: float = 0.0,
    ) -> Order | None:
        exposure = self.portfolio.exposure_pct(prices)
        decision = self.risk_manager.evaluate(
            signal, equity, exposure, len(self.portfolio.positions), current_vol_pct
        )
        if not decision.allowed or decision.position_size <= 0:
            return None
        side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL
        return self.create_order(
            signal.symbol,
            side,
            decision.position_size,
            signal.entry_price,
            signal_id=getattr(signal, "signal_id", None),
            timeframe=signal.timeframe,
        )

    def create_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        order_type: OrderType = OrderType.MARKET,
        signal_id: str | None = None,
        timeframe: str | None = None,
    ) -> Order:
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

    def fill_order(
        self,
        order_id: str,
        market_price: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        candle_quote_volume: float | None = None,
    ) -> Position | None:
        order = self.orders.get(order_id)
        if order is None or order.status not in (
            OrderStatus.OPEN,
            OrderStatus.PENDING,
            OrderStatus.PARTIAL,
        ):
            return None
        profile = self.cost_profile
        if self._legacy_profile():
            ratio = 1.0
        else:
            if candle_quote_volume is None:
                logger.warning(
                    f"Paper fill refused for {order.order_id}: "
                    "no quote volume for the entry candle."
                )
                return None
            ratio = fill_fraction(
                order.quantity * market_price,
                candle_quote_volume,
                profile.max_volume_participation,
            )
        if ratio == 0.0:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now(UTC)
            return None
        fill_price = self._entry_price(market_price, order.side)
        filled_qty = order.quantity * ratio
        fee = fill_price * filled_qty * fee_rate(profile, profile.entry_liquidity)
        order.filled_quantity = filled_qty
        order.average_fill_price = fill_price
        order.fee_paid = fee
        order.status = OrderStatus.FILLED if ratio >= 1.0 else OrderStatus.PARTIAL
        order.updated_at = datetime.now(UTC)
        side = PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT
        position = Position(
            position_id=uuid.uuid4().hex[:12],
            symbol=order.symbol,
            side=side,
            quantity=filled_qty,
            entry_price=fill_price,
            stop_loss=float(stop_loss or fill_price * 0.98),
            take_profit=float(take_profit or fill_price * 1.04),
            opened_at=datetime.now(UTC),
            signal_id=order.signal_id,
            timeframe=order.timeframe,
            risk_amount=abs(fill_price - stop_loss) * filled_qty if stop_loss else 0.0,
            fees_paid=fee,
        )
        cost = filled_qty * fill_price if side == PositionSide.LONG else 0.0
        self.portfolio.open_position(position, cost, fee)
        self.trade_history.append(
            {
                "order_id": order.order_id,
                "position_id": position.position_id,
                "symbol": order.symbol,
                "side": side.value,
                "price": fill_price,
                "quantity": filled_qty,
                "fill_fraction": ratio,
            }
        )
        return position

    def update_positions(self, prices: dict[str, float]) -> list[dict]:
        closed: list[dict] = []
        for position_id, position in list(self.portfolio.positions.items()):
            price = prices.get(position.symbol)
            if price is None:
                continue
            hit_stop = (
                price <= position.stop_loss
                if position.side == PositionSide.LONG
                else price >= position.stop_loss
            )
            hit_target = (
                price >= position.take_profit
                if position.side == PositionSide.LONG
                else price <= position.take_profit
            )
            if hit_stop or hit_target:
                exit_price = position.stop_loss if hit_stop else position.take_profit
                fee = (
                    exit_price
                    * position.quantity
                    * fee_rate(self.cost_profile, self.cost_profile.stop_exit_liquidity)
                )
                pnl = self.portfolio.close_position(position_id, exit_price, fee)
                closed.append(
                    {
                        "position_id": position_id,
                        "symbol": position.symbol,
                        "exit": exit_price,
                        "pnl": pnl,
                        "reason": "stop" if hit_stop else "target",
                    }
                )
        return closed

    def _adjusted_exit(self, exit_price: float, exit_reason: str, side: str) -> tuple[float, str]:
        profile = self.cost_profile
        if exit_reason == "target":
            liquidity = profile.target_exit_liquidity
            slippage = profile.target_exit_slippage_rate
        elif exit_reason == "stop":
            liquidity = profile.stop_exit_liquidity
            slippage = profile.market_exit_slippage_rate
        else:
            liquidity = profile.expiry_exit_liquidity
            slippage = profile.market_exit_slippage_rate
        if liquidity != "taker":
            return exit_price, liquidity
        if side == "buy":
            return exit_price * (1 - slippage), liquidity
        return exit_price * (1 + slippage), liquidity

    def resolve_position_with_candles(
        self, position_id: str, candles: list[dict[str, object]]
    ) -> dict | None:
        position = self.portfolio.positions.get(position_id)
        if position is None:
            return None
        timeframe = position.timeframe
        if timeframe is None or timeframe not in SIGNAL_EXPIRY_BY_TIMEFRAME:
            raise ValueError(f"unknown timeframe {timeframe!r}")
        side = "buy" if position.side == PositionSide.LONG else "sell"
        resolution = resolve_signal_outcome(
            candles,
            side,
            position.entry_price,
            position.stop_loss,
            position.take_profit,
            created_at=position.opened_at,
            expiry_hours=SIGNAL_EXPIRY_BY_TIMEFRAME[timeframe],
            candle_duration=candle_duration(timeframe),
        )
        if resolution.exit_reason == "no_data":
            return {
                "position_id": position_id,
                "exit": None,
                "pnl": 0.0,
                "reason": "no_data",
                "resolution": resolution,
            }
        if resolution.exit_price is None or resolution.exit_at is None:
            return None
        exit_price, liquidity = self._adjusted_exit(
            resolution.exit_price, resolution.exit_reason, side
        )
        exit_fee = exit_price * position.quantity * fee_rate(self.cost_profile, liquidity)
        holding_hours = max(0.0, (resolution.exit_at - position.opened_at).total_seconds() / 3600.0)
        funding = (
            self.cost_profile.funding_rate_per_period
            * (holding_hours / self.cost_profile.funding_period_hours)
            * position.entry_price
            * position.quantity
        )
        pnl = self.portfolio.close_position(position_id, exit_price, exit_fee + funding)
        return {
            "position_id": position_id,
            "exit": exit_price,
            "pnl": pnl,
            "reason": resolution.exit_reason,
            "exit_liquidity": liquidity,
            "fill_fraction": 1.0,
            "funding": funding,
            "resolution": resolution,
        }

    def cancel_order(self, order_id: str) -> bool:
        order = self.orders.get(order_id)
        if order is None or order.status not in (OrderStatus.OPEN, OrderStatus.PENDING):
            return False
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(UTC)
        return True
