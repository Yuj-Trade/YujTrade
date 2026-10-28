import pytest

from features.indicators.factory import IndicatorFactory
from features.indicators.trend import MovingAverageIndicator


def test_create_plain_indicator_names():
    factory = IndicatorFactory()
    names = factory.get_all_indicator_names()
    assert "rsi" in names
    assert "macd" in names
    for name in names:
        indicator = factory.create(name)
        assert indicator is not None, name


def test_create_sma_defaults_to_period_20():
    factory = IndicatorFactory()
    indicator = factory.create("sma")
    assert isinstance(indicator, MovingAverageIndicator)
    assert indicator.period == 20
    assert indicator.ma_type == "SMA"


def test_create_ema_defaults_to_period_20():
    factory = IndicatorFactory()
    indicator = factory.create("ema")
    assert isinstance(indicator, MovingAverageIndicator)
    assert indicator.period == 20
    assert indicator.ma_type == "EMA"


def test_create_parameterized_ma_names():
    factory = IndicatorFactory()
    indicator = factory.create("SMA_50")
    assert isinstance(indicator, MovingAverageIndicator)
    assert indicator.period == 50
    assert indicator.ma_type == "SMA"
    ema = factory.create("ema_9")
    assert isinstance(ema, MovingAverageIndicator)
    assert ema.period == 9


@pytest.mark.parametrize("name", ["unknown_indicator", "sma_", "ema_", "sma_x", ""])
def test_create_invalid_names_return_none(name):
    factory = IndicatorFactory()
    assert factory.create(name) is None


def test_all_indicator_names_are_lowercase():
    factory = IndicatorFactory()
    assert all(name == name.lower() for name in factory.get_all_indicator_names())
