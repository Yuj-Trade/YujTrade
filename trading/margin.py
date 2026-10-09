from dataclasses import dataclass
from typing import Dict


@dataclass
class MarginState:
    equity: float
    used_margin: float
    free_margin: float
    margin_level_pct: float
    liquidation_risk: bool


class MarginManager:
    def __init__(self, max_leverage: float = 3.0, margin_call_level: float = 100.0, liquidation_level: float = 50.0):
        self.max_leverage = float(max_leverage)
        self.margin_call_level = float(margin_call_level)
        self.liquidation_level = float(liquidation_level)

    def evaluate(self, equity: float, notional: float) -> MarginState:
        used = notional / self.max_leverage if self.max_leverage else notional
        free = equity - used
        level = (equity / used * 100.0) if used > 0 else 9999.0
        return MarginState(
            equity=float(equity),
            used_margin=float(used),
            free_margin=float(free),
            margin_level_pct=float(level),
            liquidation_risk=bool(level < self.liquidation_level),
        )

    def allowed_notional(self, equity: float) -> float:
        return float(equity * self.max_leverage)

    def margin_call(self, equity: float, notional: float) -> bool:
        return self.evaluate(equity, notional).margin_level_pct < self.margin_call_level
