from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from common.core import (
    FundamentalAnalysis,
    SignalType,
    TradingSignal,
    TrendDirection,
    TrendStrength,
)
from services.trading_service import size_signal_for
from trading.portfolio import PortfolioManager
from trading.risk_manager import RiskManager, build_risk_config


def _signal(entry=50_000.0, stop=40_000.0, target=80_000.0, side=SignalType.BUY) -> TradingSignal:
    return TradingSignal(
        symbol="BTC/USDT",
        signal_type=side,
        entry_price=entry,
        exit_price=target,
        stop_loss=stop,
        timestamp=datetime.now(UTC),
        timeframe="1d",
        confidence_score=90.0,
        reasons=["test"],
        risk_reward_ratio=3.0,
        predicted_profit=6.0,
        volume_analysis={"volume_ratio": 1.5},
        market_context={
            "trend": TrendDirection.BULLISH,
            "trend_strength": TrendStrength.STRONG,
            "market_condition": "neutral",
        },
        dynamic_levels={},
        fundamental_analysis=FundamentalAnalysis(),
    )


def _risk_manager() -> RiskManager:
    from config.settings import ConfigManager

    return RiskManager(build_risk_config(ConfigManager()))


def test_size_signal_matches_paper_risk_path():
    portfolio = PortfolioManager(1_000_000.0)
    amount, reason = size_signal_for(_signal(), portfolio, _risk_manager())
    assert reason == "ok"
    assert amount > 0


def test_size_signal_reports_a_risk_limit_not_a_crash():
    portfolio = PortfolioManager(10_000.0)
    manager = MagicMock()
    decision = MagicMock()
    decision.allowed = False
    decision.position_size = 0.0
    decision.reason = "limit:single_position"
    manager.evaluate.return_value = decision
    amount, reason = size_signal_for(_signal(), portfolio, manager)
    assert amount == 0.0
    assert reason == "limit:single_position"


def test_size_signal_uses_price_dictionary():
    portfolio = MagicMock()
    portfolio.equity.return_value = 10_000.0
    portfolio.exposure_pct.return_value = 0.0
    portfolio.positions = {}
    manager = MagicMock()
    decision = MagicMock()
    decision.allowed = True
    decision.position_size = 0.25
    manager.evaluate.return_value = decision
    amount, reason = size_signal_for(_signal(), portfolio, manager)
    assert amount == pytest.approx(0.25)
    assert reason == "ok"
    portfolio.equity.assert_called_once_with({"BTC/USDT": 50_000.0})
    portfolio.exposure_pct.assert_called_once_with({"BTC/USDT": 50_000.0})


def test_size_signal_handles_portfolio_failure():
    portfolio = MagicMock()
    portfolio.equity.side_effect = AttributeError("equity() takes 2 positional arguments")
    amount, reason = size_signal_for(_signal(), portfolio, MagicMock())
    assert amount == 0.0
    assert reason == "portfolio_unavailable"


def test_trading_service_size_signal_delegates():
    from services.trading_service import TradingService

    service = TradingService.__new__(TradingService)
    service.portfolio = PortfolioManager(1_000_000.0)
    service.risk_manager = _risk_manager()
    amount, reason = service.size_signal(_signal())
    assert reason == "ok"
    assert amount > 0


def test_equity_call_contract_is_single_argument():
    portfolio = PortfolioManager(10_000.0)
    assert portfolio.equity({"BTC/USDT": 50_000.0}) == pytest.approx(10_000.0)
