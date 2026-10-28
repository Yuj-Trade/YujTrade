import pytest

from common.core import SignalType
from trading.risk_manager import RiskConfig, RiskManager, build_risk_config


def make_signal(**overrides):
    from datetime import UTC, datetime

    from common.core import TradingSignal

    payload = {
        "symbol": "BTC/USDT",
        "signal_type": SignalType.BUY,
        "entry_price": 100.0,
        "exit_price": 120.0,
        "stop_loss": 95.0,
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        "timeframe": "1d",
        "confidence_score": 80.0,
        "reasons": ["test"],
        "risk_reward_ratio": 4.0,
        "predicted_profit": 20.0,
        "volume_analysis": {},
        "market_context": {},
        "dynamic_levels": {},
    }
    payload.update(overrides)
    return TradingSignal(**payload)


def test_risk_config_defaults():
    config = RiskConfig()
    assert config.risk_per_trade_pct == 1.0
    assert config.max_concurrent_positions == 6
    assert config.max_leverage == 3.0
    assert config.min_risk_reward == 2.0


def test_build_risk_config_defaults_for_missing_keys():
    config = build_risk_config({})
    assert config.risk_per_trade_pct == 1.0
    assert config.max_portfolio_exposure_pct == 60.0
    assert config.max_leverage == 3.0


def test_build_risk_config_reads_overrides():
    source = {
        "risk_per_trade_pct": 0.5,
        "max_portfolio_exposure_pct": 30,
        "max_single_position_pct": 8,
        "max_concurrent_positions": "3",
        "max_daily_loss_pct": 2,
        "max_weekly_loss_pct": 5,
        "max_drawdown_pct": 10,
        "max_leverage": 2,
        "min_risk_reward": 1.5,
    }
    config = build_risk_config(source)
    assert config.risk_per_trade_pct == 0.5
    assert config.max_concurrent_positions == 3
    assert config.min_risk_reward == 1.5


def test_update_state_tracks_peak():
    manager = RiskManager()
    manager.update_state(1000.0, 0.0, 0.0)
    manager.update_state(2000.0, 0.0, 0.0)
    assert manager.equity_peak == 2000.0


def test_drawdown_pct_zero_without_peak():
    assert RiskManager().drawdown_pct(1000.0) == 0.0


def test_drawdown_pct_after_decline():
    manager = RiskManager()
    manager.update_state(2000.0, 0.0, 0.0)
    assert manager.drawdown_pct(1500.0) == pytest.approx(25.0)


def test_size_multiplier_full_by_default():
    assert RiskManager().size_multiplier() == 1.0


def test_size_multiplier_half_after_loss_streak():
    manager = RiskManager()
    manager.update_state(1000.0, 0.0, 0.0, consecutive_losses=3)
    assert manager.size_multiplier() == 0.5


def test_size_multiplier_half_on_weekly_loss():
    manager = RiskManager()
    manager.update_state(1000.0, 0.0, -6.0)
    assert manager.size_multiplier() == 0.5


def test_fixed_fractional_size():
    manager = RiskManager()
    assert manager.fixed_fractional_size(10000.0, 100.0, 95.0) == pytest.approx(20.0)


def test_fixed_fractional_size_zero_on_bad_inputs():
    manager = RiskManager()
    assert manager.fixed_fractional_size(10000.0, 100.0, 100.0) == 0.0
    assert manager.fixed_fractional_size(0.0, 100.0, 95.0) == 0.0


def test_volatility_adjusted_size_clamped_low():
    manager = RiskManager()
    assert manager.volatility_adjusted_size(10.0, 100.0) == pytest.approx(2.5)


def test_volatility_adjusted_size_clamped_high():
    manager = RiskManager()
    assert manager.volatility_adjusted_size(10.0, 0.5) == pytest.approx(20.0)


def test_volatility_adjusted_size_passthrough_on_zero_vol():
    manager = RiskManager()
    assert manager.volatility_adjusted_size(10.0, 0.0) == 10.0


def test_kelly_size_positive_edge():
    manager = RiskManager()
    size = manager.kelly_size(10000.0, 100.0, 95.0, win_rate=0.6, payoff=2.0)
    assert size == pytest.approx(100.0)


def test_kelly_size_clamped_at_five_percent():
    manager = RiskManager()
    size = manager.kelly_size(10000.0, 100.0, 95.0, win_rate=0.99, payoff=10.0)
    assert size == pytest.approx(100.0)


def test_kelly_size_zero_when_no_edge():
    manager = RiskManager()
    assert manager.kelly_size(10000.0, 100.0, 95.0, win_rate=0.1, payoff=1.0) == 0.0


def test_kelly_size_zero_on_bad_inputs():
    manager = RiskManager()
    assert manager.kelly_size(10000.0, 100.0, 95.0, 0.5, 0.0) == 0.0
    assert manager.kelly_size(0.0, 100.0, 95.0, 0.5, 2.0) == 0.0


def test_check_limits_all_pass():
    manager = RiskManager()
    checks = manager.check_limits(10000.0, 10.0, 2, 5.0)
    assert checks == {
        "drawdown": True,
        "daily_loss": True,
        "weekly_loss": True,
        "exposure": True,
        "single_position": True,
        "concurrent": True,
    }


def test_check_limits_failures_named():
    manager = RiskManager()
    checks = manager.check_limits(10000.0, 70.0, 6, 15.0)
    assert checks["exposure"] is False
    assert checks["single_position"] is False
    assert checks["concurrent"] is False


def test_evaluate_rejects_hold_signal():
    manager = RiskManager()
    signal = make_signal(signal_type=SignalType.HOLD)
    decision = manager.evaluate(signal, 10000.0, 0.0, 0)
    assert decision.allowed is False
    assert decision.reason == "hold_signal"


def test_evaluate_rejects_low_risk_reward():
    manager = RiskManager()
    signal = make_signal(risk_reward_ratio=1.5)
    decision = manager.evaluate(signal, 10000.0, 0.0, 0)
    assert decision.reason == "low_rr"


def test_evaluate_rejects_zero_equity():
    manager = RiskManager()
    decision = manager.evaluate(make_signal(), 0.0, 0.0, 0)
    assert decision.reason == "no_equity"


def test_evaluate_reports_failed_limit():
    manager = RiskManager()
    decision = manager.evaluate(make_signal(), 10000.0, 0.0, 0)
    assert decision.allowed is False
    assert decision.reason == "limit:single_position"
    assert decision.checks["single_position"] is False


def test_evaluate_allows_small_signal():
    manager = RiskManager(RiskConfig(risk_per_trade_pct=0.5))
    decision = manager.evaluate(make_signal(), 10000.0, 0.0, 0)
    assert decision.allowed is True
    assert decision.position_size == pytest.approx(10.0)
    assert decision.risk_amount == pytest.approx(50.0)
    assert decision.leverage == 1.0
    assert decision.reason == "long"


def test_evaluate_allows_short_signal():
    manager = RiskManager(RiskConfig(risk_per_trade_pct=0.5))
    signal = make_signal(
        signal_type=SignalType.SELL,
        entry_price=100.0,
        stop_loss=105.0,
        exit_price=80.0,
        risk_reward_ratio=4.0,
    )
    decision = manager.evaluate(signal, 10000.0, 0.0, 0)
    assert decision.allowed is True
    assert decision.reason == "short"
    assert decision.position_size == pytest.approx(10.0)


def test_evaluate_size_halves_after_loss_streak():
    plain = RiskManager(RiskConfig(risk_per_trade_pct=1.0))
    streaked = RiskManager(RiskConfig(risk_per_trade_pct=1.0))
    streaked.update_state(10000.0, 0.0, 0.0, consecutive_losses=3)
    assert plain.fixed_fractional_size(10000.0, 100.0, 95.0) == pytest.approx(20.0)
    assert streaked.fixed_fractional_size(10000.0, 100.0, 95.0) == pytest.approx(10.0)
