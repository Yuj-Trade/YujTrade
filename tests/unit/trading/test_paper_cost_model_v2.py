"""Cost-model-v2 in the paper engine and the report (P3)."""

from datetime import UTC, datetime, timedelta

import pytest

from application.performance_report import PerformanceConfig, build_performance_report
from common.core import (
    OrderSide,
    OrderStatus,
    PositionSide,
    SignalType,
    TradingSignal,
)
from config.settings import ConfigManager
from domain.costs import CostProfile, cost_profile_from_config, legacy_report_profile
from domain.performance import ResolutionRecord
from services.trading_service import build_cost_profile
from trading.paper_trading import PaperTradingEngine
from trading.portfolio import PortfolioManager

PROFILE = CostProfile(
    version="cost-model-v2",
    maker_fee_rate=0.001,
    taker_fee_rate=0.001,
    entry_liquidity="taker",
    target_exit_liquidity="maker",
    stop_exit_liquidity="taker",
    expiry_exit_liquidity="taker",
    entry_slippage_rate=0.0005,
    market_exit_slippage_rate=0.0005,
    target_exit_slippage_rate=0.0,
    funding_rate_per_period=0.0001,
    funding_period_hours=8.0,
    max_volume_participation=0.05,
)


def _engine(profile=PROFILE) -> PaperTradingEngine:
    return PaperTradingEngine(
        portfolio=PortfolioManager(100000.0),
        fee_rate=0.001,
        slippage_rate=0.0005,
        cost_profile=profile,
    )


def _order(engine, quantity=10.0, side=OrderSide.BUY):
    return engine.create_order("BTC/USDT", side, quantity, 100.0, timeframe="1h")


def _signal() -> TradingSignal:
    return TradingSignal(
        symbol="BTC/USDT",
        signal_type=SignalType.BUY,
        entry_price=100.0,
        exit_price=120.0,
        stop_loss=90.0,
        timestamp=datetime.now(UTC),
        timeframe="1h",
        confidence_score=90.0,
        reasons=["trend"],
        risk_reward_ratio=3.0,
        predicted_profit=20.0,
        volume_analysis={"volume_ratio": 2.0},
        market_context={"trend_strength": "STRONG"},
        dynamic_levels={},
    )


def test_a_taker_entry_pays_entry_slippage():
    engine = _engine()
    order = _order(engine)

    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=1e9)

    assert position is not None
    assert position.entry_price == pytest.approx(100.0 * 1.0005)
    assert order.status is OrderStatus.FILLED


def test_a_sell_entry_pays_entry_slippage_downwards():
    engine = _engine()
    order = _order(engine, side=OrderSide.SELL)

    position = engine.fill_order(order.order_id, 100.0, 110.0, 80.0, candle_quote_volume=1e9)

    assert position is not None
    assert position.entry_price == pytest.approx(100.0 * (1 - 0.0005))


def test_a_maker_target_exit_is_not_slipped():
    engine = _engine()
    order = _order(engine)
    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=1e9)
    opened = position.opened_at
    candles = [
        {
            "timestamp": opened + timedelta(hours=index),
            "open": 100.0,
            "high": 121.0 if index == 2 else 101.0,
            "low": 99.0,
            "close": 100.0,
        }
        for index in range(13)
    ]

    result = engine.resolve_position_with_candles(position.position_id, candles)

    assert result is not None
    assert result["reason"] == "target"
    assert result["exit"] == pytest.approx(120.0)
    assert result["exit_liquidity"] == "maker"


def test_a_market_stop_exit_is_slipped_adversely():
    engine = _engine()
    order = _order(engine)
    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=1e9)
    opened = position.opened_at
    candles = [
        {
            "timestamp": opened + timedelta(hours=index),
            "open": 100.0,
            "high": 101.0,
            "low": 89.0 if index == 1 else 99.0,
            "close": 100.0,
        }
        for index in range(13)
    ]

    result = engine.resolve_position_with_candles(position.position_id, candles)

    assert result is not None
    assert result["reason"] == "stop"
    assert result["exit"] == pytest.approx(90.0 * (1 - 0.0005))
    assert result["exit_liquidity"] == "taker"


def test_funding_is_charged_at_close():
    engine = _engine()
    order = _order(engine)
    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=1e9)
    opened = position.opened_at
    candles = [
        {
            "timestamp": opened + timedelta(hours=index),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
        }
        for index in range(13)
    ]

    result = engine.resolve_position_with_candles(position.position_id, candles)

    assert result is not None
    holding = (result["resolution"].exit_at - opened).total_seconds() / 3600.0
    expected = 0.0001 * (holding / 8.0) * position.entry_price * position.quantity
    assert result["funding"] == pytest.approx(expected)


def test_a_partial_fill_keeps_the_fraction_and_discards_the_remainder():
    engine = _engine()
    order = _order(engine, quantity=10.0)

    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=500.0)

    assert position is not None
    fraction = 0.05 * 500.0 / 1000.0
    assert position.quantity == pytest.approx(10.0 * fraction)
    assert order.status is OrderStatus.PARTIAL
    assert order.filled_quantity == pytest.approx(10.0 * fraction)
    assert len(engine.portfolio.positions) == 1


def test_a_zero_fill_cancels_the_order():
    engine = _engine()
    order = _order(engine)

    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=0.0)

    assert position is None
    assert order.status is OrderStatus.CANCELLED
    assert engine.portfolio.positions == {}


def test_a_missing_volume_refuses_the_fill_and_leaves_the_order_open():
    engine = _engine()
    order = _order(engine)

    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0)

    assert position is None
    assert order.status is OrderStatus.OPEN


def test_the_legacy_profile_fills_without_a_volume():
    engine = _engine(legacy_report_profile(0.001, 0.0005))
    order = _order(engine)

    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0)

    assert position is not None
    assert order.status is OrderStatus.FILLED
    assert position.entry_price == pytest.approx(100.0 * 1.0005)


def test_the_engine_rejects_a_naive_position_timeframe():
    engine = _engine()
    order = engine.create_order("BTC/USDT", OrderSide.BUY, 1.0, 100.0, timeframe=None)
    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=1e9)

    with pytest.raises(ValueError):
        engine.resolve_position_with_candles(position.position_id, [])


def test_the_engine_has_no_dead_funding_method():
    engine = _engine()
    assert not hasattr(engine, "apply_funding")
    assert not hasattr(engine, "funding_rate_per_day")


def test_the_engine_keeps_the_required_cost_arguments():
    with pytest.raises(TypeError):
        PaperTradingEngine()


def test_build_cost_profile_reads_the_nested_defaults(tmp_path):
    config = ConfigManager(
        config_path=str(tmp_path / "config.json"),
        weights_path=str(tmp_path / "weights.json"),
    )
    config.set("paper_cost_model", {"taker_fee_rate": 0.004})

    profile = build_cost_profile(config)

    assert profile.taker_fee_rate == 0.004
    assert (
        profile.maker_fee_rate == ConfigManager.DEFAULT_CONFIG["paper_cost_model"]["maker_fee_rate"]
    )
    assert profile.version == "cost-model-v2"


def test_cost_profile_from_config_fills_every_default_key():
    defaults = ConfigManager.DEFAULT_CONFIG["paper_cost_model"]
    profile = cost_profile_from_config({}, defaults)
    assert profile.version == defaults["version"]
    assert profile.max_volume_participation == defaults["max_volume_participation"]


def test_the_paper_engine_result_reports_the_cost_fields():
    engine = _engine()
    order = _order(engine)
    position = engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=1e9)
    opened = position.opened_at
    candles = [
        {
            "timestamp": opened + timedelta(hours=index),
            "open": 100.0,
            "high": 121.0,
            "low": 99.0,
            "close": 100.0,
        }
        for index in range(13)
    ]

    result = engine.resolve_position_with_candles(position.position_id, candles)

    assert set(result) >= {
        "reason",
        "exit",
        "pnl",
        "exit_liquidity",
        "fill_fraction",
        "funding",
        "resolution",
    }


def test_the_report_uses_the_supplied_profile():
    record = ResolutionRecord(
        signal_id="sig-1",
        symbol="BTC/USDT",
        timeframe="1h",
        side="buy",
        entry=100.0,
        stop=90.0,
        target=120.0,
        created_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
        exit_at=datetime(2026, 10, 1, 14, tzinfo=UTC),
        exit_price=120.0,
        exit_reason="target",
        candles_used=4,
        resolver_version="paper-resolution-v1",
        entry_quote_volume=1e9,
    )
    config = PerformanceConfig(
        initial_cash=10000.0,
        risk_per_trade_pct=1.0,
        fee_rate=0.001,
        slippage_rate=0.0005,
        rf_annual=0.0,
        periods_per_year=365.0,
        min_trades_for_ratios=30,
        cost_profile=PROFILE,
    )

    report = build_performance_report([record], config, datetime(2026, 10, 20, tzinfo=UTC))

    assert report.parameters["cost_model_version"] == "cost-model-v2"
    assert report.coverage["legacy_full_fill_records"] == 0


def test_a_legacy_report_profile_is_used_when_none_is_supplied():
    config = PerformanceConfig(
        initial_cash=10000.0,
        risk_per_trade_pct=1.0,
        fee_rate=0.001,
        slippage_rate=0.0005,
        rf_annual=0.0,
        periods_per_year=365.0,
        min_trades_for_ratios=30,
    )
    assert config.effective_profile().version == "legacy-report-v1"


def test_partial_fill_is_recorded_in_the_trade_history():
    engine = _engine()
    order = _order(engine)
    engine.fill_order(order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=500.0)

    history = engine.trade_history[-1]
    assert history["fill_fraction"] == pytest.approx(0.025)


def test_a_long_and_a_short_position_resolve_with_their_own_side():
    engine = _engine()
    long_order = _order(engine, quantity=1.0)
    long_position = engine.fill_order(
        long_order.order_id, 100.0, 90.0, 120.0, candle_quote_volume=1e9
    )
    assert long_position.side is PositionSide.LONG
    short_order = _order(engine, quantity=1.0, side=OrderSide.SELL)
    short_position = engine.fill_order(
        short_order.order_id, 100.0, 110.0, 80.0, candle_quote_volume=1e9
    )
    assert short_position.side is PositionSide.SHORT
