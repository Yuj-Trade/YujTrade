# ADR-0002: Live and backtest parity

Outcome resolution is stop-first and is implemented by `domain.outcome`. Paper
and backtest callers must pass the same candle shape and signal parameters.
