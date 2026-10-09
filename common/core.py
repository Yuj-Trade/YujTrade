from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


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
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    fee_paid: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_id: Optional[str] = None
    timeframe: Optional[str] = None
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
    signal_id: Optional[str] = None
    timeframe: Optional[str] = None
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
    checks: Dict[str, Any] = field(default_factory=dict)



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
    mvrv: Optional[float] = None
    sopr: Optional[float] = None
    active_addresses: Optional[int] = None
    realized_cap: Optional[float] = None


@dataclass
class OrderBook:
    bids: List[Tuple[float, float]] = field(default_factory=list)
    asks: List[Tuple[float, float]] = field(default_factory=list)
    bid_ask_spread: Optional[float] = None
    total_bid_volume: Optional[float] = None
    total_ask_volume: Optional[float] = None


@dataclass
class BinanceFuturesData:
    top_trader_long_short_ratio_accounts: Optional[float] = None
    top_trader_long_short_ratio_positions: Optional[float] = None
    liquidation_orders: List[Dict[str, Any]] = field(default_factory=list)
    mark_price: Optional[float] = None


@dataclass
class DerivativesAnalysis:
    open_interest: Optional[float] = None
    funding_rate: Optional[float] = None
    taker_long_short_ratio: Optional[float] = None
    coingecko_derivatives: List[Dict[str, Any]] = field(default_factory=list)
    binance_futures_data: Optional[BinanceFuturesData] = None
    cumulative_funding_rate: Optional[float] = None


@dataclass
class MacroEconomicData:
    cpi: Optional[float] = None
    fed_rate: Optional[float] = None
    treasury_yield_10y: Optional[float] = None
    gdp: Optional[float] = None
    unemployment: Optional[float] = None


@dataclass
class TrendingData:
    coingecko_trending: List[str] = field(default_factory=list)


@dataclass
class MarketAnalysis:
    trend: TrendDirection
    trend_strength: TrendStrength
    volatility: float
    volume_trend: str
    support_levels: List[float]
    resistance_levels: List[float]
    momentum_score: float
    market_condition: MarketCondition
    trend_acceleration: float
    volume_confirmation: bool
    hurst_exponent: Optional[float] = None
    volume_trend_score: Optional[float] = None
    volume_ratio: Optional[float] = None
    adx: Optional[float] = None
    candle_patterns: List[str] = field(default_factory=list)


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
    reasons: List[str]
    risk_reward_ratio: float
    predicted_profit: float
    volume_analysis: Dict[str, float]
    market_context: Dict[str, Any]
    dynamic_levels: Dict[str, float]
    fundamental_analysis: Optional[FundamentalAnalysis] = None
    on_chain_analysis: Optional[OnChainAnalysis] = None
    derivatives_analysis: Optional[DerivativesAnalysis] = None
    order_book: Optional[OrderBook] = None
    macro_data: Optional[MacroEconomicData] = None
    trending_data: Optional[TrendingData] = None
    market_indices: Optional[Dict[str, Any]] = None
    ml_confidence: Optional[float] = None
    threshold_used: Optional[float] = None
    threshold_regime: Optional[str] = None
    expiry_time: Optional[datetime] = None
    position_size: Optional[float] = None
    data_collection_timestamp: Optional[datetime] = None
    analysis_timestamp: Optional[datetime] = None
