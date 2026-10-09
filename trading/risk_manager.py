from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from common.core import PositionSide, RiskDecision, SignalType, TradingSignal


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 1.0
    max_portfolio_exposure_pct: float = 60.0
    max_single_position_pct: float = 10.0
    max_concurrent_positions: int = 6
    max_daily_loss_pct: float = 4.0
    max_weekly_loss_pct: float = 10.0
    max_drawdown_pct: float = 20.0
    max_leverage: float = 3.0
    min_risk_reward: float = 2.0
    volatility_target_pct: float = 2.0
    kelly_fraction: float = 0.5


def build_risk_config(config_manager: Any) -> RiskConfig:
    get = config_manager.get
    return RiskConfig(
        risk_per_trade_pct=float(get("risk_per_trade_pct", 1.0)),
        max_portfolio_exposure_pct=float(get("max_portfolio_exposure_pct", 60.0)),
        max_single_position_pct=float(get("max_single_position_pct", 10.0)),
        max_concurrent_positions=int(get("max_concurrent_positions", 6)),
        max_daily_loss_pct=float(get("max_daily_loss_pct", 4.0)),
        max_weekly_loss_pct=float(get("max_weekly_loss_pct", 10.0)),
        max_drawdown_pct=float(get("max_drawdown_pct", 20.0)),
        max_leverage=float(get("max_leverage", 3.0)),
        min_risk_reward=float(get("min_risk_reward", 2.0)),
    )


class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.equity_peak = 0.0
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.consecutive_losses = 0

    def update_state(self, equity: float, daily_pnl: float, weekly_pnl: float, consecutive_losses: int = 0):
        if equity > self.equity_peak:
            self.equity_peak = equity
        self.daily_pnl = daily_pnl
        self.weekly_pnl = weekly_pnl
        self.consecutive_losses = consecutive_losses

    def drawdown_pct(self, equity: float) -> float:
        if self.equity_peak <= 0:
            return 0.0
        return max(0.0, (self.equity_peak - equity) / self.equity_peak * 100.0)

    def size_multiplier(self) -> float:
        if self.consecutive_losses >= 3:
            return 0.5
        if self.weekly_pnl <= -self.config.max_weekly_loss_pct * 0.5:
            return 0.5
        return 1.0

    def fixed_fractional_size(self, equity: float, entry: float, stop: float) -> float:
        price_risk = abs(entry - stop)
        if price_risk <= 0 or equity <= 0:
            return 0.0
        risk_amount = equity * self.config.risk_per_trade_pct / 100.0 * self.size_multiplier()
        return risk_amount / price_risk

    def volatility_adjusted_size(self, base_size: float, current_vol_pct: float) -> float:
        if current_vol_pct <= 0:
            return base_size
        factor = self.config.volatility_target_pct / current_vol_pct
        factor = max(0.25, min(2.0, factor))
        return base_size * factor

    def kelly_size(self, equity: float, entry: float, stop: float, win_rate: float, payoff: float) -> float:
        if payoff <= 0 or equity <= 0:
            return 0.0
        p = max(0.01, min(0.99, win_rate))
        q = 1.0 - p
        f = (p * payoff - q) / payoff * self.config.kelly_fraction
        f = max(0.0, min(0.05, f))
        price_risk = abs(entry - stop)
        if price_risk <= 0:
            return 0.0
        return equity * f / price_risk

    def check_limits(self, equity: float, open_exposure_pct: float, open_count: int, new_position_pct: float) -> Dict[str, Any]:
        checks: Dict[str, Any] = {}
        checks["drawdown"] = self.drawdown_pct(equity) < self.config.max_drawdown_pct
        checks["daily_loss"] = self.daily_pnl > -self.config.max_daily_loss_pct
        checks["weekly_loss"] = self.weekly_pnl > -self.config.max_weekly_loss_pct
        checks["exposure"] = (open_exposure_pct + new_position_pct) <= self.config.max_portfolio_exposure_pct
        checks["single_position"] = new_position_pct <= self.config.max_single_position_pct
        checks["concurrent"] = open_count < self.config.max_concurrent_positions
        return checks

    def evaluate(self, signal: TradingSignal, equity: float, open_exposure_pct: float, open_count: int, current_vol_pct: float = 0.0, win_rate: float = 0.5, payoff: float = 2.0) -> RiskDecision:
        if signal.signal_type not in (SignalType.BUY, SignalType.SELL):
            return RiskDecision(allowed=False, reason="hold_signal")
        if signal.risk_reward_ratio < self.config.min_risk_reward:
            return RiskDecision(allowed=False, reason="low_rr")
        if equity <= 0:
            return RiskDecision(allowed=False, reason="no_equity")
        entry = signal.entry_price
        stop = signal.stop_loss
        base = self.fixed_fractional_size(equity, entry, stop)
        sized = self.volatility_adjusted_size(base, current_vol_pct)
        kelly = self.kelly_size(equity, entry, stop, win_rate, payoff)
        if kelly > 0:
            sized = min(sized, max(sized * 0.5, kelly))
        notional = sized * entry
        new_position_pct = notional / equity * 100.0 if equity > 0 else 100.0
        checks = self.check_limits(equity, open_exposure_pct, open_count, new_position_pct)
        if not all(checks.values()):
            failed = [k for k, v in checks.items() if not v]
            return RiskDecision(allowed=False, reason="limit:" + ",".join(failed), checks=checks)
        leverage = min(self.config.max_leverage, max(1.0, notional / equity)) if equity > 0 else 1.0
        risk_amount = abs(entry - stop) * sized
        side = PositionSide.LONG if signal.signal_type == SignalType.BUY else PositionSide.SHORT
        return RiskDecision(allowed=True, position_size=float(sized), risk_amount=float(risk_amount), leverage=float(leverage), reason=side.value, checks=checks)
