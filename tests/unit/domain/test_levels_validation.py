import math

import pytest

from domain.gates import normalize_confidence
from domain.levels import validate_levels
from domain.types import ReasonCode


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 0.0, -1.0])
@pytest.mark.parametrize("slot", ["entry", "stop", "target"])
def test_non_finite_or_non_positive_price_is_rejected(bad, slot):
    values = {"entry": 100.0, "stop": 95.0, "target": 110.0}
    values[slot] = bad
    reason = validate_levels("buy", values["entry"], values["stop"], values["target"])
    assert reason is ReasonCode.NON_FINITE_PRICE


def test_buy_valid_ordering_passes():
    assert validate_levels("buy", 100.0, 95.0, 110.0) is None


def test_sell_valid_ordering_passes():
    assert validate_levels("sell", 100.0, 105.0, 90.0) is None


@pytest.mark.parametrize(
    ("side", "entry", "stop", "target"),
    [
        ("buy", 100.0, 100.0, 110.0),
        ("buy", 100.0, 95.0, 100.0),
        ("buy", 100.0, 105.0, 110.0),
        ("buy", 100.0, 95.0, 90.0),
        ("sell", 100.0, 100.0, 90.0),
        ("sell", 100.0, 95.0, 90.0),
        ("sell", 100.0, 105.0, 110.0),
        ("sell", 100.0, 105.0, 100.0),
    ],
)
def test_wrong_ordering_or_equal_boundary_is_invalid(side, entry, stop, target):
    assert validate_levels(side, entry, stop, target) is ReasonCode.INVALID_LEVELS


def test_unknown_side_is_invalid():
    assert validate_levels("hold", 100.0, 95.0, 110.0) is ReasonCode.INVALID_LEVELS


def test_side_is_case_insensitive():
    assert validate_levels("BUY", 100.0, 95.0, 110.0) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0.0),
        ("abc", 0.0),
        (-5.0, 0.0),
        (0.0, 0.0),
        (0.5, 50.0),
        (1.0, 100.0),
        (42.0, 42.0),
        (250.0, 100.0),
        (math.nan, 0.0),
        (math.inf, 0.0),
        (-math.inf, 0.0),
    ],
)
def test_normalize_confidence_scale_and_clamp(raw, expected):
    assert normalize_confidence(raw) == pytest.approx(expected)
