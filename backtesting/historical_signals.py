from typing import Any

from common.constants import LONG_TERM_CONFIG


async def generate_historical_signals(
    data: Any,
    symbol: str,
    timeframe: str,
    generator: Any,
    step: int = 1,
    include_external: bool = False,
    include_ml: bool = False,
) -> tuple[list[Any], dict[str, int]]:
    minimum = int(LONG_TERM_CONFIG.get("min_data_points", {}).get(timeframe, 300))
    start = max(minimum, 1)
    signals: list[Any] = []
    rejected = {"no_signal": 0, "errors": 0}
    for end in range(start, len(data), step):
        window = data.iloc[: end + 1]
        try:
            signal = await generator.generate_signal(
                symbol,
                timeframe,
                window,
                include_external=include_external,
                include_ml=include_ml,
            )
        except Exception:
            rejected["errors"] += 1
            continue
        if signal is None:
            rejected["no_signal"] += 1
        else:
            signals.append(signal)
    return signals, rejected
