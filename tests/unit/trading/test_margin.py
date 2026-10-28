import pytest

from trading.margin import MarginManager, MarginState


@pytest.fixture
def manager() -> MarginManager:
    return MarginManager()


def test_defaults():
    manager = MarginManager()
    assert manager.max_leverage == 3.0
    assert manager.margin_call_level == 100.0
    assert manager.liquidation_level == 50.0


def test_evaluate_uses_notional_over_leverage(manager):
    state = manager.evaluate(equity=1000.0, notional=3000.0)
    assert state.used_margin == pytest.approx(1000.0)
    assert state.free_margin == pytest.approx(0.0)
    assert state.margin_level_pct == pytest.approx(100.0)
    assert state.liquidation_risk is False


def test_evaluate_flags_liquidation_risk(manager):
    state = manager.evaluate(equity=400.0, notional=3000.0)
    assert state.used_margin == pytest.approx(1000.0)
    assert state.margin_level_pct == pytest.approx(40.0)
    assert state.liquidation_risk is True


def test_evaluate_with_zero_notional_reports_max_level(manager):
    state = manager.evaluate(equity=1000.0, notional=0.0)
    assert state.margin_level_pct == 9999.0
    assert state.free_margin == pytest.approx(1000.0)
    assert state.liquidation_risk is False


def test_zero_leverage_uses_full_notional_as_used():
    manager = MarginManager(max_leverage=0.0)
    state = manager.evaluate(equity=3000.0, notional=2000.0)
    assert state.used_margin == pytest.approx(2000.0)
    assert state.margin_level_pct == pytest.approx(150.0)


def test_margin_call_boundary_is_not_triggered(manager):
    assert manager.margin_call(1000.0, 3000.0) is False


def test_margin_call_triggers_below_level(manager):
    assert manager.margin_call(400.0, 3000.0) is True


def test_allowed_notional_scales_with_leverage(manager):
    assert manager.allowed_notional(1000.0) == pytest.approx(3000.0)


def test_evaluate_returns_margin_state(manager):
    assert isinstance(manager.evaluate(equity=1000.0, notional=100.0), MarginState)


def test_custom_levels_are_coerced_to_float():
    manager = MarginManager(max_leverage=5, margin_call_level=80, liquidation_level=20)
    assert isinstance(manager.max_leverage, float)
    assert isinstance(manager.margin_call_level, float)
    assert isinstance(manager.liquidation_level, float)
    assert manager.evaluate(1000.0, 5000.0).used_margin == pytest.approx(1000.0)
