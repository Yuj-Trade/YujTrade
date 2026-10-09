import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SizingConfig:
    risk_per_trade_pct: float
    max_single_position_pct: float
    max_portfolio_exposure_pct: float
    max_leverage: float


@dataclass(frozen=True)
class SizingResult:
    quantity: float
    reason: str | None


def calculate_position_size(
    equity: float,
    entry: float,
    stop: float,
    config: SizingConfig,
    current_exposure: float = 0.0,
) -> SizingResult:
    if equity <= 0 or entry <= 0 or entry == stop:
        return SizingResult(0.0, "size_zero")
    raw = (equity * config.risk_per_trade_pct / 100.0) / abs(entry - stop)
    max_single = equity * config.max_single_position_pct / 100.0 / entry
    remaining = max(0.0, equity * config.max_portfolio_exposure_pct / 100.0 - current_exposure)
    max_exposure = remaining / entry
    max_leverage = equity * config.max_leverage / entry
    quantity = math.floor(min(raw, max_single, max_exposure, max_leverage))
    return SizingResult(float(quantity), "size_zero" if quantity <= 0 else None)
