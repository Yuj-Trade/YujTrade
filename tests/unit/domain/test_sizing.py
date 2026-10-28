import dataclasses
import math

import pytest

from domain.sizing import SizingConfig, SizingResult, calculate_position_size


@pytest.fixture
def config() -> SizingConfig:
    return SizingConfig(
        risk_per_trade_pct=1.0,
        max_single_position_pct=20.0,
        max_portfolio_exposure_pct=50.0,
        max_leverage=5.0,
    )


def test_dataclasses_are_frozen():
    config = SizingConfig(1.0, 20.0, 50.0, 5.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.risk_per_trade_pct = 2.0
    result = SizingResult(1.0, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.quantity = 2.0


@pytest.mark.parametrize(
    ("equity", "entry", "stop"),
    [
        (0.0, 100.0, 95.0),
        (-1000.0, 100.0, 95.0),
        (1000.0, 0.0, 95.0),
        (1000.0, 100.0, 100.0),
    ],
)
def test_degenerate_inputs_return_size_zero(equity, entry, stop, config):
    result = calculate_position_size(equity, entry, stop, config)
    assert result.quantity == 0.0
    assert result.reason == "size_zero"


def test_risk_based_quantity_when_caps_not_binding(config):
    result = calculate_position_size(10000.0, 100.0, 90.0, config)
    assert result.quantity == 10.0
    assert result.reason is None


def test_quantity_is_floored_to_whole_units():
    open_caps_config = SizingConfig(
        risk_per_trade_pct=1.0,
        max_single_position_pct=100.0,
        max_portfolio_exposure_pct=100.0,
        max_leverage=100.0,
    )
    result = calculate_position_size(1000.0, 100.0, 97.0, open_caps_config)
    assert result.quantity == 3.0
    assert result.reason is None


def test_existing_exposure_reduces_max_exposure_cap(config):
    free = calculate_position_size(10000.0, 100.0, 90.0, config)
    capped = calculate_position_size(10000.0, 100.0, 90.0, config, current_exposure=4500.0)
    assert free.quantity == 10.0
    assert capped.quantity == 5.0
    assert capped.reason is None


def test_exposure_fully_utilized_blocks_new_position(config):
    result = calculate_position_size(10000.0, 100.0, 90.0, config, current_exposure=5000.0)
    assert result.quantity == 0.0
    assert result.reason == "size_zero"


def test_max_single_position_cap_binds(config):
    result = calculate_position_size(10000.0, 10.0, 9.9, config)
    assert result.quantity == 200.0
    assert math.isfinite(result.quantity)


def test_max_leverage_cap_binds():
    config = SizingConfig(
        risk_per_trade_pct=50.0,
        max_single_position_pct=100.0,
        max_portfolio_exposure_pct=100.0,
        max_leverage=2.0,
    )
    result = calculate_position_size(10000.0, 10.0, 9.0, config)
    assert result.quantity == 1000.0
    assert result.reason is None


def test_oversized_current_exposure_floor_is_zero(config):
    result = calculate_position_size(10000.0, 100.0, 90.0, config, current_exposure=99999.0)
    assert result.quantity == 0.0
    assert result.reason == "size_zero"
