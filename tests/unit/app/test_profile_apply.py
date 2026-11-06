import pytest

from app.profile_service import APPLIED_NOTE, RESTART_NOTE, ProfileService
from config.profile_schema import chained_getter
from config.settings import ConfigManager
from services.trading_service import build_risk_config
from trading.paper_trading import PaperTradingEngine
from trading.portfolio import PortfolioManager
from trading.risk_manager import RiskManager

RISK_KEYS = [
    "risk_per_trade_pct",
    "max_concurrent_positions",
    "loss_streak_threshold",
    "loss_streak_size_multiplier",
    "weekly_loss_reduction_ratio",
]


@pytest.fixture
def config(tmp_path):
    manager = ConfigManager(config_path=str(tmp_path / "config.json"))
    return manager


@pytest.fixture
def engine():
    return PaperTradingEngine(
        portfolio=PortfolioManager(),
        risk_manager=RiskManager(),
        fee_rate=0.001,
        slippage_rate=0.0005,
    )


class FakeService:
    def __init__(self, engine):
        self.risk_manager = engine.risk_manager
        self.paper_engine = engine
        self.exchange_service = None


def test_risk_values_update_the_existing_risk_manager_in_place(config, engine):
    service = ProfileService(config, FakeService(engine))
    risk_manager = engine.risk_manager
    ok, note, applied = service.save("risk_per_trade_pct", "2.5")
    assert ok is True
    assert note == APPLIED_NOTE
    assert applied == APPLIED_NOTE
    assert risk_manager.config.risk_per_trade_pct == 2.5
    assert engine.risk_manager is risk_manager
    assert build_risk_config(config).risk_per_trade_pct == 2.5


def test_loss_streak_parameters_are_applied_in_place(config, engine):
    service = ProfileService(config, FakeService(engine))
    ok, _, _ = service.save("loss_streak_threshold", "5")
    assert ok is True
    ok, _, _ = service.save("loss_streak_size_multiplier", "0.25")
    assert ok is True
    config_risk = engine.risk_manager.config
    assert config_risk.loss_streak_threshold == 5
    assert config_risk.loss_streak_size_multiplier == 0.25
    engine.risk_manager.update_state(1000.0, 0.0, 0.0, consecutive_losses=4)
    assert engine.risk_manager.size_multiplier() == 1.0
    engine.risk_manager.update_state(1000.0, 0.0, 0.0, consecutive_losses=5)
    assert engine.risk_manager.size_multiplier() == 0.25


def test_weekly_loss_reduction_uses_the_stored_ratio(config, engine):
    service = ProfileService(config, FakeService(engine))
    service.save("weekly_loss_reduction_ratio", "0.2")
    service.save("max_weekly_loss_pct", "10")
    engine.risk_manager.update_state(1000.0, 0.0, -3.0)
    assert engine.risk_manager.size_multiplier() == 0.2


def test_cost_model_values_update_the_paper_engine_profile(config, engine):
    service = ProfileService(config, FakeService(engine))
    ok, _, applied = service.save("taker_fee_rate", "0.004")
    assert ok is True
    assert applied == APPLIED_NOTE
    assert engine.cost_profile.taker_fee_rate == 0.004
    assert engine.cost_profile.maker_fee_rate == 0.001
    version = engine.cost_profile.version
    assert version != "legacy-report-v1"


def test_cost_model_rejects_an_invalid_liquidity_choice(config, engine):
    service = ProfileService(config, FakeService(engine))
    ok, message, applied = service.save("entry_liquidity", "both")
    assert ok is False
    assert message
    assert applied == ""


def test_initial_cash_reports_after_restart(config, engine):
    service = ProfileService(config, FakeService(engine))
    ok, note, applied = service.save("initial_cash", "20000")
    assert ok is True
    assert note == RESTART_NOTE
    assert applied == RESTART_NOTE
    assert config.get("initial_cash") == 20000.0


@pytest.mark.parametrize(
    "key", ["coingecko_api_tier", "schedule_hour", "outcome_notifications_mode"]
)
def test_startup_cached_keys_report_after_restart(config, engine, key):
    service = ProfileService(config, FakeService(engine))
    raw = "pro" if key == "coingecko_api_tier" else "*/6" if key == "schedule_hour" else "shadow"
    ok, note, applied = service.save(key, raw)
    assert ok is True
    assert note == RESTART_NOTE
    assert applied == RESTART_NOTE


def test_schedule_and_notification_keys_report_after_restart(config, engine):
    service = ProfileService(config, FakeService(engine))
    ok, note, _ = service.save("enable_scheduled_analysis", "on")
    assert ok is True
    assert note == RESTART_NOTE


def test_gate_overrides_reach_the_gate_config(config):
    from application.gate_config import build_gate_config
    from common.constants import LONG_TERM_CONFIG

    service = ProfileService(config, None)
    base = build_gate_config(chained_getter(config, LONG_TERM_CONFIG.get), "1d")
    assert base.min_confidence == 72.0
    service.save("min_confidence_by_timeframe", "{1d: 95}")
    overridden = build_gate_config(chained_getter(config, LONG_TERM_CONFIG.get), "1d")
    assert overridden.min_confidence == 95.0
    service.save("min_trend_strength", "STRONG")
    overridden = build_gate_config(chained_getter(config, LONG_TERM_CONFIG.get), "1d")
    assert overridden.min_trend_strength == "STRONG"


def test_analysis_timeframes_follow_the_override(config):
    from services.trading_service import TradingService

    service = TradingService.__new__(TradingService)
    service.config_manager = config
    assert service._analysis_timeframes() == ["1d", "1w", "1M"]
    config.set("full_analyze_timeframes", ["1h", "4h"])
    assert service._analysis_timeframes() == ["1h", "4h"]


def test_signal_gate_default_matches_the_long_term_constant(tmp_path):
    from application.gate_config import build_gate_config
    from common.constants import LONG_TERM_CONFIG

    manager = ConfigManager(config_path=str(tmp_path / "config.json"))
    service_like = LONG_TERM_CONFIG
    config_gate = build_gate_config(chained_getter(manager, service_like.get), "1h")
    constant_gate = build_gate_config(service_like.get, "1h")
    assert config_gate.min_confidence == constant_gate.min_confidence
    assert config_gate.min_trend_strength == constant_gate.min_trend_strength
    assert config_gate.min_volume_surge == constant_gate.min_volume_surge


def test_operator_only_key_cannot_be_saved(config, engine):
    service = ProfileService(config, FakeService(engine))
    for key in ("exchange_access_profile", "execution_dry_run", "exchange_attested_keys"):
        ok, message, _ = service.save(key, "live")
        assert ok is False
        assert message
    assert config.config == {**ConfigManager.DEFAULT_CONFIG}
