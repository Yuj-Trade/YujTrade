import tests.mocks.pandas_ta_mock  # Mock pandas_ta before any real imports
"""
import tests.mocks.pandas_ta_mock  # Mock pandas_ta before any real imports
Pytest configuration and shared fixtures for YujTrade tests.

CRITICAL: This file ensures no test connects to real external services.
All secrets, API keys, and Redis connections are monkeypatched to fake values.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Session-scoped monkeypatches for secrets/config ───

# These must run BEFORE any config/settings imports
os.environ.setdefault("REDIS_HOST", "fake-redis-host")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_TOKEN", "")
os.environ.setdefault("BINANCE_API_KEY", "")
os.environ.setdefault("BINANCE_API_SECRET", "")
os.environ.setdefault("COINGECKO_API_KEY", "")
os.environ.setdefault("ALPHAVANTAGE_API_KEY", "")
os.environ.setdefault("CRYPTOPANIC_API_KEY", "")
os.environ.setdefault("MESSARI_API_KEY", "")
os.environ.setdefault("COINDESK_API_KEY", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake_token:fake")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "123456789")


@pytest.fixture(scope="session", autouse=True)
def _patch_secrets_early():
    """Patch secrets before any module imports ConfigManager/SecretsManager."""
    with patch("config.settings.SecretsManager.get_secret") as mock_get_secret:
        mock_get_secret.side_effect = lambda key, default=None, cast=str: {
            "REDIS_HOST": "fake-redis-host",
            "REDIS_PORT": 6379,
            "REDIS_TOKEN": "",
            "BINANCE_API_KEY": "",
            "BINANCE_API_SECRET": "",
            "COINGECKO_API_KEY": "",
            "ALPHAVANTAGE_API_KEY": "",
            "CRYPTOPANIC_API_KEY": "",
            "MESSARI_API_KEY": "",
            "COINDESK_API_KEY": "",
            "TELEGRAM_BOT_TOKEN": "fake_token:fake",
            "TELEGRAM_ADMIN_CHAT_ID": "123456789",
        }.get(key, default)
        yield


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ─── OHLCV Fixtures ───

@pytest.fixture
def valid_1h_ohlcv() -> pd.DataFrame:
    """Valid 1h OHLCV data with >= min_data_points (600)."""
    dates = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=600,
        freq="1h",
        tz="UTC"
    )
    np.random.seed(42)
    base = 50000
    returns = np.random.normal(0, 0.01, 600)
    prices = base * np.exp(np.cumsum(returns))

    df = pd.DataFrame({
        "open": prices * (1 + np.random.uniform(-0.002, 0.002, 600)),
        "high": prices * (1 + np.random.uniform(0, 0.005, 600)),
        "low": prices * (1 - np.random.uniform(0, 0.005, 600)),
        "close": prices,
        "volume": np.random.uniform(100, 10000, 600),
    }, index=dates)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


@pytest.fixture
def valid_1d_ohlcv() -> pd.DataFrame:
    """Valid 1d OHLCV data with >= min_data_points (300)."""
    dates = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=300,
        freq="1D",
        tz="UTC"
    )
    np.random.seed(42)
    base = 50000
    returns = np.random.normal(0, 0.02, 300)
    prices = base * np.exp(np.cumsum(returns))

    df = pd.DataFrame({
        "open": prices * (1 + np.random.uniform(-0.01, 0.01, 300)),
        "high": prices * (1 + np.random.uniform(0, 0.02, 300)),
        "low": prices * (1 - np.random.uniform(0, 0.02, 300)),
        "close": prices,
        "volume": np.random.uniform(1000, 100000, 300),
    }, index=dates)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


@pytest.fixture
def insufficient_ohlcv() -> pd.DataFrame:
    """OHLCV with fewer rows than min_data_points."""
    dates = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=50,
        freq="1h",
        tz="UTC"
    )
    np.random.seed(42)
    base = 50000
    prices = base * np.exp(np.cumsum(np.random.normal(0, 0.01, 50)))

    return pd.DataFrame({
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": np.random.uniform(100, 10000, 50),
    }, index=dates)


@pytest.fixture
def missing_columns_ohlcv() -> pd.DataFrame:
    """OHLCV missing required columns."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h", tz="UTC")
    return pd.DataFrame({"open": [1]*100, "high": [1]*100}, index=dates)


@pytest.fixture
def high_less_than_low_ohlcv() -> pd.DataFrame:
    """OHLCV with high < low (invalid)."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h", tz="UTC")
    return pd.DataFrame({
        "open": [50000]*100,
        "high": [49000]*100,
        "low": [51000]*100,
        "close": [50000]*100,
        "volume": [1000]*100,
    }, index=dates)


@pytest.fixture
def zero_or_negative_price_ohlcv() -> pd.DataFrame:
    """OHLCV with zero or negative prices."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h", tz="UTC")
    prices = np.ones(100) * 50000
    prices[50] = 0
    prices[51] = -100
    return pd.DataFrame({
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": [1000]*100,
    }, index=dates)


@pytest.fixture
def extreme_single_candle_ohlcv() -> pd.DataFrame:
    """OHLCV with >75% single candle move (warning only)."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h", tz="UTC")
    prices = np.ones(100) * 50000
    prices[50] = 10000  # 80% drop
    return pd.DataFrame({
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": [1000]*100,
    }, index=dates)


@pytest.fixture
def low_volume_ohlcv() -> pd.DataFrame:
    """OHLCV with mean volume < 1 (warning only)."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h", tz="UTC")
    return pd.DataFrame({
        "open": [50000]*100,
        "high": [50500]*100,
        "low": [49500]*100,
        "close": [50000]*100,
        "volume": [0.1]*100,
    }, index=dates)


@pytest.fixture
def stale_ohlcv() -> pd.DataFrame:
    """OHLCV with last timestamp older than freshness threshold."""
    old_date = datetime.now(timezone.utc) - timedelta(days=10)
    dates = pd.date_range(end=old_date, periods=100, freq="1h", tz="UTC")
    return pd.DataFrame({
        "open": [50000]*100,
        "high": [50500]*100,
        "low": [49500]*100,
        "close": [50000]*100,
        "volume": [1000]*100,
    }, index=dates)


@pytest.fixture
def duplicate_timestamps_ohlcv() -> pd.DataFrame:
    """OHLCV with duplicate timestamps."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=99, freq="1h", tz="UTC")
    dates = dates.insert(50, dates[50])  # duplicate
    return pd.DataFrame({
        "open": [50000]*100,
        "high": [50500]*100,
        "low": [49500]*100,
        "close": [50000]*100,
        "volume": [1000]*100,
    }, index=dates)


@pytest.fixture
def large_gap_ohlcv() -> pd.DataFrame:
    """OHLCV with gap_ratio > 0.1 (should raise ValueError)."""
    # Create data with a large gap (missing ~20% of candles)
    dates1 = pd.date_range(
        end=datetime.now(timezone.utc) - timedelta(days=5),
        periods=400,
        freq="1h",
        tz="UTC"
    )
    dates2 = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=400,
        freq="1h",
        tz="UTC"
    )
    dates = dates1.union(dates2)
    prices = np.ones(len(dates)) * 50000
    return pd.DataFrame({
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": [1000]*len(dates),
    }, index=dates)


@pytest.fixture
def small_gap_ohlcv() -> pd.DataFrame:
    """OHLCV with small gap (0 < gap_ratio <= 0.1, penalty only)."""
    dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq="1h", tz="UTC")
    dates = dates.delete(50)  # remove one candle (1% gap)
    return pd.DataFrame({
        "open": [50000]*99,
        "high": [50500]*99,
        "low": [49500]*99,
        "close": [50000]*99,
        "volume": [1000]*99,
    }, index=dates)


# ─── TradingSignal Fixtures ───

@pytest.fixture
def buy_valid_signal() -> Dict[str, Any]:
    """Valid BUY TradingSignal with all fields populated."""
    from common.core import SignalType
    return {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 50000.0,
        "exit_price": 55000.0,
        "stop_loss": 48000.0,
        "timestamp": datetime.now(timezone.utc),
        "timeframe": "1d",
        "confidence_score": 75.0,
        "reasons": ["RSI oversold", "MACD bullish crossover"],
        "risk_reward_ratio": 3.0,
        "predicted_profit": 10.0,
        "volume_analysis": {"volume_ratio": 1.5},
        "market_context": {
            "trend": "bullish",
            "trend_strength": "strong",
            "volatility": 2.5,
            "market_condition": "oversold",
        },
        "dynamic_levels": {
            "primary_entry": 50000.0,
            "secondary_entry": 49500.0,
            "primary_exit": 55000.0,
            "secondary_exit": 56000.0,
            "tight_stop": 48000.0,
            "wide_stop": 47000.0,
            "breakeven_point": 50500.0,
        },
        "fundamental_analysis": None,
        "on_chain_analysis": None,
        "derivatives_analysis": None,
        "order_book": None,
        "macro_data": None,
        "trending_data": None,
        "market_indices": None,
        "ml_confidence": None,
        "threshold_used": 72.0,
        "threshold_regime": "low|persistent",
        "expiry_time": None,
        "position_size": None,
        "data_collection_timestamp": None,
        "analysis_timestamp": None,
    }


@pytest.fixture
def sell_valid_signal() -> Dict[str, Any]:
    """Valid SELL TradingSignal with all fields populated."""
    from common.core import SignalType
    return {
        "symbol": "ETH/USDT",
        "signal_type": SignalType.SELL,
        "entry_price": 3000.0,
        "exit_price": 2700.0,
        "stop_loss": 3150.0,
        "timestamp": datetime.now(timezone.utc),
        "timeframe": "1d",
        "confidence_score": 78.0,
        "reasons": ["RSI overbought", "Bearish divergence"],
        "risk_reward_ratio": 3.0,
        "predicted_profit": 10.0,
        "volume_analysis": {"volume_ratio": 1.3},
        "market_context": {
            "trend": "bearish",
            "trend_strength": "strong",
            "volatility": 3.0,
            "market_condition": "overbought",
        },
        "dynamic_levels": {
            "primary_entry": 3000.0,
            "secondary_entry": 3050.0,
            "primary_exit": 2700.0,
            "secondary_exit": 2600.0,
            "tight_stop": 3150.0,
            "wide_stop": 3200.0,
            "breakeven_point": 2950.0,
        },
        "fundamental_analysis": None,
        "on_chain_analysis": None,
        "derivatives_analysis": None,
        "order_book": None,
        "macro_data": None,
        "trending_data": None,
        "market_indices": None,
        "ml_confidence": None,
        "threshold_used": 72.0,
        "threshold_regime": "high|mean_reverting",
        "expiry_time": None,
        "position_size": None,
        "data_collection_timestamp": None,
        "analysis_timestamp": None,
    }


@pytest.fixture
def signal_with_macro_data() -> Dict[str, Any]:
    """Signal with macro data for SignalRanking fed_rate tests."""
    from common.core import SignalType, MacroEconomicData
    signal = {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 50000.0,
        "exit_price": 55000.0,
        "stop_loss": 48000.0,
        "timestamp": datetime.now(timezone.utc),
        "timeframe": "1d",
        "confidence_score": 75.0,
        "reasons": ["Technical bullish"],
        "risk_reward_ratio": 3.0,
        "predicted_profit": 10.0,
        "volume_analysis": {"volume_ratio": 1.5},
        "market_context": {
            "trend": "bullish",
            "trend_strength": "strong",
            "volatility": 2.5,
            "market_condition": "oversold",
        },
        "dynamic_levels": {
            "primary_entry": 50000.0,
            "secondary_entry": 49500.0,
            "primary_exit": 55000.0,
            "secondary_exit": 56000.0,
            "tight_stop": 48000.0,
            "wide_stop": 47000.0,
            "breakeven_point": 50500.0,
        },
        "macro_data": MacroEconomicData(fed_rate=4.5, cpi=3.2),
        "fundamental_analysis": None,
        "on_chain_analysis": None,
        "derivatives_analysis": None,
        "order_book": None,
        "trending_data": None,
        "market_indices": None,
        "ml_confidence": None,
        "threshold_used": 72.0,
        "threshold_regime": "low|persistent",
        "expiry_time": None,
        "position_size": None,
        "data_collection_timestamp": None,
        "analysis_timestamp": None,
    }
    return signal


@pytest.fixture
def signal_without_external_data() -> Dict[str, Any]:
    """Signal with all external data None (for backtest path)."""
    from common.core import SignalType
    return {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 50000.0,
        "exit_price": 55000.0,
        "stop_loss": 48000.0,
        "timestamp": datetime.now(timezone.utc),
        "timeframe": "1d",
        "confidence_score": 75.0,
        "reasons": ["Technical bullish"],
        "risk_reward_ratio": 3.0,
        "predicted_profit": 10.0,
        "volume_analysis": {"volume_ratio": 1.5},
        "market_context": {
            "trend": "bullish",
            "trend_strength": "strong",
            "volatility": 2.5,
            "market_condition": "oversold",
        },
        "dynamic_levels": {
            "primary_entry": 50000.0,
            "secondary_entry": 49500.0,
            "primary_exit": 55000.0,
            "secondary_exit": 56000.0,
            "tight_stop": 48000.0,
            "wide_stop": 47000.0,
            "breakeven_point": 50500.0,
        },
        "fundamental_analysis": None,
        "on_chain_analysis": None,
        "derivatives_analysis": None,
        "order_book": None,
        "macro_data": None,
        "trending_data": None,
        "market_indices": None,
        "ml_confidence": None,
        "threshold_used": 72.0,
        "threshold_regime": "low|persistent",
        "expiry_time": None,
        "position_size": None,
        "data_collection_timestamp": None,
        "analysis_timestamp": None,
    }


# ─── MarketAnalysis Fixtures ───

@pytest.fixture
def bullish_strong_analysis() -> Dict[str, Any]:
    """Strong bullish MarketAnalysis."""
    from common.core import TrendDirection, TrendStrength, MarketCondition
    return {
        "trend": TrendDirection.BULLISH,
        "trend_strength": TrendStrength.STRONG,
        "volatility": 2.5,
        "volume_trend": "increasing",
        "support_levels": [49000, 48000],
        "resistance_levels": [52000, 55000],
        "momentum_score": 0.5,
        "market_condition": MarketCondition.OVERSOLD,
        "trend_acceleration": 0.1,
        "volume_confirmation": True,
        "hurst_exponent": 0.6,
        "volume_trend_score": 0.3,
        "volume_ratio": 1.5,
        "adx": 30.0,
        "candle_patterns": ["hammer (bullish)", "engulfing (bullish)"],
    }


@pytest.fixture
def bearish_strong_analysis() -> Dict[str, Any]:
    """Strong bearish MarketAnalysis."""
    from common.core import TrendDirection, TrendStrength, MarketCondition
    return {
        "trend": TrendDirection.BEARISH,
        "trend_strength": TrendStrength.STRONG,
        "volatility": 3.0,
        "volume_trend": "decreasing",
        "support_levels": [28000, 27000],
        "resistance_levels": [31000, 32000],
        "momentum_score": -0.5,
        "market_condition": MarketCondition.OVERBOUGHT,
        "trend_acceleration": -0.1,
        "volume_confirmation": True,
        "hurst_exponent": 0.6,
        "volume_trend_score": -0.3,
        "volume_ratio": 0.8,
        "adx": 35.0,
        "candle_patterns": ["shooting star (bearish)", "engulfing (bearish)"],
    }


@pytest.fixture
def sideways_weak_analysis() -> Dict[str, Any]:
    """Weak sideways MarketAnalysis."""
    from common.core import TrendDirection, TrendStrength, MarketCondition
    return {
        "trend": TrendDirection.SIDEWAYS,
        "trend_strength": TrendStrength.WEAK,
        "volatility": 1.5,
        "volume_trend": "stable",
        "support_levels": [49000, 48500],
        "resistance_levels": [51000, 52000],
        "momentum_score": 0.0,
        "market_condition": MarketCondition.NEUTRAL,
        "trend_acceleration": 0.0,
        "volume_confirmation": False,
        "hurst_exponent": 0.5,
        "volume_trend_score": 0.0,
        "volume_ratio": 1.0,
        "adx": 15.0,
        "candle_patterns": [],
    }


@pytest.fixture
def market_analysis_hurst_low() -> Dict[str, Any]:
    """MarketAnalysis with hurst_exponent < 0.45 (mean-reverting)."""
    from common.core import TrendDirection, TrendStrength, MarketCondition
    return {
        "trend": TrendDirection.SIDEWAYS,
        "trend_strength": TrendStrength.WEAK,
        "volatility": 1.5,
        "volume_trend": "stable",
        "support_levels": [49000],
        "resistance_levels": [51000],
        "momentum_score": 0.0,
        "market_condition": MarketCondition.NEUTRAL,
        "trend_acceleration": 0.0,
        "volume_confirmation": False,
        "hurst_exponent": 0.3,
        "volume_trend_score": 0.0,
        "volume_ratio": 1.0,
        "adx": 10.0,
        "candle_patterns": [],
    }


@pytest.fixture
def market_analysis_hurst_mid() -> Dict[str, Any]:
    """MarketAnalysis with hurst_exponent 0.45-0.55 (random walk)."""
    from common.core import TrendDirection, TrendStrength, MarketCondition
    return {
        "trend": TrendDirection.SIDEWAYS,
        "trend_strength": TrendStrength.WEAK,
        "volatility": 1.5,
        "volume_trend": "stable",
        "support_levels": [49000],
        "resistance_levels": [51000],
        "momentum_score": 0.0,
        "market_condition": MarketCondition.NEUTRAL,
        "trend_acceleration": 0.0,
        "volume_confirmation": False,
        "hurst_exponent": 0.5,
        "volume_trend_score": 0.0,
        "volume_ratio": 1.0,
        "adx": 10.0,
        "candle_patterns": [],
    }


@pytest.fixture
def market_analysis_hurst_high() -> Dict[str, Any]:
    """MarketAnalysis with hurst_exponent > 0.55 (persistent)."""
    from common.core import TrendDirection, TrendStrength, MarketCondition
    return {
        "trend": TrendDirection.BULLISH,
        "trend_strength": TrendStrength.STRONG,
        "volatility": 2.5,
        "volume_trend": "increasing",
        "support_levels": [49000],
        "resistance_levels": [52000],
        "momentum_score": 0.5,
        "market_condition": MarketCondition.OVERSOLD,
        "trend_acceleration": 0.1,
        "volume_confirmation": True,
        "hurst_exponent": 0.7,
        "volume_trend_score": 0.3,
        "volume_ratio": 1.5,
        "adx": 30.0,
        "candle_patterns": [],
    }


# ─── Model Prediction Fixtures ───

@pytest.fixture
def model_prediction_full() -> Dict[str, float]:
    """Full model prediction with all fields (for gap 33)."""
    return {
        "prediction": 51000.0,
        "confidence": 75.0,  # final_confidence = calibrated * (1 - uncertainty^2)
        "raw_confidence": 70.0,
        "calibrated_confidence": 80.0,
        "uncertainty": 0.2,
    }


@pytest.fixture
def model_prediction_calibrated_equals_confidence() -> Dict[str, float]:
    """Prediction where calibrated_confidence == confidence (ambiguous behavior)."""
    return {
        "prediction": 51000.0,
        "confidence": 75.0,
        "raw_confidence": 75.0,
        "calibrated_confidence": 75.0,
        "uncertainty": 0.0,
    }


@pytest.fixture
def model_prediction_calibrated_diverges() -> Dict[str, float]:
    """Prediction where calibrated_confidence != confidence (tests gap 33)."""
    return {
        "prediction": 51000.0,
        "confidence": 60.0,  # final = calibrated * (1 - uncertainty^2)
        "raw_confidence": 70.0,
        "calibrated_confidence": 80.0,
        "uncertainty": 0.5,  # 80 * (1 - 0.25) = 60
    }


# ─── External Data Bundle Fixtures ───

@pytest.fixture
def external_data_full() -> Dict[str, Any]:
    """Full external data bundle with all sources."""
    from common.core import (
        DerivativesAnalysis, FundamentalAnalysis, OnChainAnalysis,
        OrderBook, MacroEconomicData, TrendingData
    )
    return {
        "news": {"score": 5.0, "fear_greed_index": 50},
        "derivatives": DerivativesAnalysis(
            funding_rate=0.005,
            taker_long_short_ratio=1.2,
            open_interest=1000000,
        ),
        "fundamental": FundamentalAnalysis(
            market_cap=1_000_000_000,
            total_volume=500_000_000,
            developer_score=80,
            community_score=90,
        ),
        "onchain": OnChainAnalysis(mvrv=2.5, sopr=1.02),
        "order_book": OrderBook(
            total_bid_volume=1000, total_ask_volume=800, bid_ask_spread=0.5
        ),
        "macro": MacroEconomicData(fed_rate=3.5, cpi=2.8),
        "trending": TrendingData(coingecko_trending=["BTC", "ETH", "SOL"]),
        "market_indices": {
            "BTC.D": 55.0,
            "USDT.D": 5.0,
            "DXY": 103.0,
            "VIX": 20.0,
            "DEFI_TVL": 50_000_000_000,
        },
    }


@pytest.fixture
def external_data_partial() -> Dict[str, Any]:
    """Partial external data with some None values."""
    from common.core import DerivativesAnalysis, MacroEconomicData
    return {
        "news": {"score": 5.0, "fear_greed_index": 50},
        "derivatives": DerivativesAnalysis(funding_rate=0.005),
        "fundamental": None,
        "onchain": None,
        "order_book": None,
        "macro": MacroEconomicData(fed_rate=3.5),
        "trending": None,
        "market_indices": {"BTC.D": 55.0},
    }


@pytest.fixture
def external_data_all_none() -> Dict[str, Any]:
    """All external data None (for include_external=False path)."""
    return {
        "news": None,
        "derivatives": None,
        "fundamental": None,
        "onchain": None,
        "order_book": None,
        "macro": None,
        "trending": None,
        "market_indices": None,
    }


# ─── Mock Fixtures ───

@pytest.fixture
def mock_fetcher():
    """Mock fetcher for testing."""
    fetcher = AsyncMock()
    fetcher.fetch = AsyncMock(return_value=pd.DataFrame())
    fetcher.close = AsyncMock()
    return fetcher


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=True)
    redis_mock.close = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    return redis_mock


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram bot for testing."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


# ─── Helper Fixtures ───

@pytest.fixture
def mock_config_manager():
    """Mock ConfigManager with test defaults."""
    from config.settings import ConfigManager
    config = MagicMock(spec=ConfigManager)
    config.get_component_weights.return_value = {
        "technical_analysis": 0.4,
        "market_context": 0.2,
        "external_data": 0.2,
        "ml_models": 0.2,
    }
    config.get_indicator_weights.return_value = {}
    config.get_cache_ttl.return_value = 3600
    config.DEFAULT_CONFIG = {
        "model_data_limits": {
            "1h": 2000, "4h": 1500, "1d": 1000, "1w": 500, "1M": 300
        },
        "model_prediction_limit": 500,
        "app_version": "1.0.0",
    }
    config.DEFAULT_WEIGHTS_CONFIG = {
        "cache_config": {
            "ohlcv": 3600, "external": 7200, "model": 1800
        }
    }
    return config


# ─── Test Markers ───

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "talib: test requires TA-Lib")
    config.addinivalue_line("markers", "integration: integration test")
    config.addinivalue_line("markers", "slow: slow test")


# ─── Test Utilities ───

class AsyncContextManager:
    """Helper for async context managers in tests."""
    def __init__(self, obj):
        self.obj = obj

    async def __aenter__(self):
        return self.obj

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def async_context_manager():
    return AsyncContextManager