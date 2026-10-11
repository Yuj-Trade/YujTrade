from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    fee_paid: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_id: str | None = None
    timeframe: str | None = None
    paper: bool = True
    notes: str = ""


@dataclass
class Position:
    position_id: str
    symbol: str
    side: PositionSide
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_id: str | None = None
    timeframe: str | None = None
    leverage: float = 1.0
    risk_amount: float = 0.0
    fees_paid: float = 0.0


@dataclass
class RiskDecision:
    allowed: bool
    position_size: float = 0.0
    risk_amount: float = 0.0
    leverage: float = 1.0
    reason: str = ""
    checks: dict[str, Any] = field(default_factory=dict)


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class TrendDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


class MarketCondition(Enum):
    OVERSOLD = "oversold"
    OVERBOUGHT = "overbought"
    NEUTRAL = "neutral"


class TrendStrength(Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


@dataclass
class IndicatorResult:
    name: str
    value: float
    signal_strength: float
    interpretation: str


@dataclass
class FundamentalAnalysis:
    market_cap: float = 0.0
    total_volume: float = 0.0
    developer_score: float = 0.0
    community_score: float = 0.0


@dataclass
class OnChainAnalysis:
    mvrv: float | None = None
    sopr: float | None = None
    active_addresses: int | None = None
    realized_cap: float | None = None


@dataclass
class OrderBook:
    bids: list[tuple[float, float]] = field(default_factory=list)
    asks: list[tuple[float, float]] = field(default_factory=list)
    bid_ask_spread: float | None = None
    total_bid_volume: float | None = None
    total_ask_volume: float | None = None


@dataclass
class BinanceFuturesData:
    top_trader_long_short_ratio_accounts: float | None = None
    top_trader_long_short_ratio_positions: float | None = None
    liquidation_orders: list[dict[str, Any]] = field(default_factory=list)
    mark_price: float | None = None


@dataclass
class DerivativesAnalysis:
    open_interest: float | None = None
    funding_rate: float | None = None
    taker_long_short_ratio: float | None = None
    coingecko_derivatives: list[dict[str, Any]] = field(default_factory=list)
    binance_futures_data: BinanceFuturesData | None = None
    cumulative_funding_rate: float | None = None


@dataclass
class MacroEconomicData:
    cpi: float | None = None
    fed_rate: float | None = None
    treasury_yield_10y: float | None = None
    gdp: float | None = None
    unemployment: float | None = None


@dataclass
class TrendingData:
    coingecko_trending: list[str] = field(default_factory=list)


@dataclass
class MarketAnalysis:
    trend: TrendDirection
    trend_strength: TrendStrength
    volatility: float
    volume_trend: str
    support_levels: list[float]
    resistance_levels: list[float]
    momentum_score: float
    market_condition: MarketCondition
    trend_acceleration: float
    volume_confirmation: bool
    hurst_exponent: float | None = None
    volume_trend_score: float | None = None
    volume_ratio: float | None = None
    adx: float | None = None
    candle_patterns: list[str] = field(default_factory=list)


@dataclass
class DynamicLevels:
    primary_entry: float
    secondary_entry: float
    primary_exit: float
    secondary_exit: float
    tight_stop: float
    wide_stop: float
    breakeven_point: float
    trailing_stop: float


@dataclass
class TradingSignal:
    symbol: str
    signal_type: SignalType
    entry_price: float
    exit_price: float
    stop_loss: float
    timestamp: datetime
    timeframe: str
    confidence_score: float
    reasons: list[str]
    risk_reward_ratio: float
    predicted_profit: float
    volume_analysis: dict[str, float]
    market_context: dict[str, Any]
    dynamic_levels: dict[str, float]
    fundamental_analysis: FundamentalAnalysis | None = None
    on_chain_analysis: OnChainAnalysis | None = None
    derivatives_analysis: DerivativesAnalysis | None = None
    order_book: OrderBook | None = None
    macro_data: MacroEconomicData | None = None
    trending_data: TrendingData | None = None
    market_indices: dict[str, Any] | None = None
    ml_confidence: float | None = None
    threshold_used: float | None = None
    threshold_regime: str | None = None
    expiry_time: datetime | None = None
    position_size: float | None = None
    data_collection_timestamp: datetime | None = None
    analysis_timestamp: datetime | None = None
