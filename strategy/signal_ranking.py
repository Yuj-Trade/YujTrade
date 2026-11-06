from common.constants import LONG_TERM_CONFIG
from common.core import SignalType, TradingSignal
from domain.portfolio_risk import correlation_penalty


class SignalRanking:
    @staticmethod
    def _ml_multiplier(signal: TradingSignal) -> float:
        ml_conf = getattr(signal, "ml_confidence", None)
        if ml_conf is None:
            return 1.0
        try:
            conf = float(ml_conf)
        except (TypeError, ValueError):
            return 1.0
        if conf > 1.0:
            conf /= 100.0
        conf = max(0.0, min(1.0, conf))
        return 0.95 + 0.1 * conf

    @staticmethod
    def calculate_signal_score(signal: TradingSignal) -> float:
        base_score = signal.confidence_score
        rr_multiplier = (
            min(signal.risk_reward_ratio, 5.0) / 2.0 if signal.risk_reward_ratio > 0 else 0.5
        )

        timeframe_priority = LONG_TERM_CONFIG["timeframe_priority_weights"].get(
            signal.timeframe, 1.0
        )
        base_score *= timeframe_priority

        base_score *= rr_multiplier

        base_score *= SignalRanking._ml_multiplier(signal)

        if signal.macro_data and signal.macro_data.fed_rate is not None:
            if signal.signal_type == SignalType.BUY and signal.macro_data.fed_rate > 4.0:
                base_score *= 0.8
            elif signal.signal_type == SignalType.SELL and signal.macro_data.fed_rate < 2.0:
                base_score *= 0.8

        return base_score

    @staticmethod
    def rank_signals(signals: list[TradingSignal]) -> list[TradingSignal]:
        return sorted(signals, key=SignalRanking.calculate_signal_score, reverse=True)

    @staticmethod
    def _sign(signal: TradingSignal) -> int:
        return -1 if signal.signal_type == SignalType.SELL else 1

    @staticmethod
    def select_diversified(
        signals: list[TradingSignal],
        corr: list[list[float]] | tuple[tuple[float, ...], ...],
        index: dict[str, int],
        book_weights: dict[str, float],
        budget_factors: dict[str, float],
        penalty_weight: float,
    ) -> list[TradingSignal]:
        remaining = list(signals)
        selected: list[TradingSignal] = []
        refs: list[tuple[int, int]] = []
        for symbol, weight in book_weights.items():
            if weight == 0.0 or symbol not in index:
                continue
            sign = 1 if weight > 0.0 else -1
            refs.append((index[symbol], sign))
        while remaining:
            best_position = 0
            best_score = None
            for position, signal in enumerate(remaining):
                base = SignalRanking.calculate_signal_score(signal)
                symbol = signal.symbol
                sign = SignalRanking._sign(signal)
                if symbol in index:
                    same_direction = [
                        reference for reference in refs if reference[1] == sign
                    ]
                    penalty = correlation_penalty(index[symbol], same_direction, corr)
                    factor = budget_factors.get(symbol, 1.0)
                else:
                    penalty = 0.0
                    factor = 1.0
                adjusted = base * (1.0 - penalty_weight * penalty) * factor
                if best_score is None or adjusted > best_score:
                    best_score = adjusted
                    best_position = position
            chosen = remaining.pop(best_position)
            selected.append(chosen)
            if chosen.symbol in index:
                refs.append((index[chosen.symbol], SignalRanking._sign(chosen)))
        return selected
