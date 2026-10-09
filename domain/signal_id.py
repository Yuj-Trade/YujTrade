from datetime import datetime


def make_signal_id(
    symbol: str, timeframe: str, timestamp: datetime | str, signal_type: str
) -> str:
    value = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
    return f"{symbol}|{timeframe}|{value}|{signal_type}"
