from domain.outcome import OutcomeEvent

OUTCOME_LABELS = {"target": "TP hit", "stop": "SL hit", "expired": "Expired"}


def render_outcome(
    symbol: str, timeframe: str, side: str, entry: float, event: OutcomeEvent
) -> str:
    direction = 1.0 if side == "buy" else -1.0
    lines = [
        f"{OUTCOME_LABELS[event.kind]} | {symbol} {timeframe} {side.upper()}",
        f"Entry: {entry:.8f}",
        f"Exit: {event.price:.8f} (candle {event.at.isoformat()})",
    ]
    if entry > 0:
        lines.append(f"Move: {direction * (event.price - entry) / entry * 100:+.2f}%")
    return "\n".join(lines)
