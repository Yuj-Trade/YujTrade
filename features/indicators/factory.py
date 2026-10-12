from features.indicators.all_indicators import get_all_indicators
from features.indicators.base import TechnicalIndicator
from features.indicators.trend import MovingAverageIndicator


class IndicatorFactory:
    def __init__(self):
        self._indicator_classes: dict[str, type[TechnicalIndicator]] = get_all_indicators()

    def create(self, name: str) -> TechnicalIndicator | None:
        name_lower = name.lower()

        if name_lower.startswith(("sma_", "ema_")):
            try:
                ma_type, period_str = name_lower.split("_")
                period = int(period_str)
                return MovingAverageIndicator(period=period, ma_type=ma_type)
            except (ValueError, IndexError):
                return None

        indicator_class = self._indicator_classes.get(name_lower)
        if indicator_class:
            if name_lower in ("sma", "ema"):
                return indicator_class(period=20, ma_type=name_lower)
            return indicator_class()

        return None

    def get_all_indicator_names(self) -> list[str]:
        return list(self._indicator_classes.keys())
