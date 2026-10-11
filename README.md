# YujTrade
Long-term crypto trading signal engine with Telegram delivery.
## Phases
P0: ML leakage fixes, dynamic levels, risk, paper trading, execution, walk-forward, tests
P1: service wiring, slippage-aware backtest, Telegram commands, secrets hardening, metrics, Docker
P2: docs, packaging, CI hardening
## Architecture
Market Data -> Validation -> Indicators -> Scoring -> Signal -> MTF -> Ranking -> Risk -> Portfolio -> Paper/Live -> PnL -> Calibration
## Quickstart
1. Copy `.env.example` to `.env` and set tokens
2. `pip install -r requirements.txt`
3. `python -m pytest -m "not slow and not ml" -q`
4. `python main.py`
## Configuration
`ConfigManager` defaults plus env: risk_per_trade_pct, max_portfolio_exposure_pct, max_single_position_pct, max_concurrent_positions, max_daily_loss_pct, max_weekly_loss_pct, max_drawdown_pct, max_leverage, initial_cash, execution_dry_run.
## Paper trading
Default mode is paper via `TradingService.execute_signal(signal, mode="paper")`. Live execution stays dry-run unless `execution_dry_run=false` with exchange credentials.
## Risk
Fixed fractional + volatility cap + Kelly ceiling, portfolio exposure limits, daily/weekly/drawdown halts.
## Backtest
`BacktestingEngine.run_backtest` supports commission + slippage. `EventDrivenSimulator`
in `backtesting/simulator.py` is the deterministic event-loop engine (entry at next open,
stop-first, gap-aware exits). `WalkForwardValidator.split` validates across chronological
windows with purge (`label_horizon`) and embargo. `scripts/run_holdout.py` guards the final
15% holdout (`--confirm`, `--force-rerun`). Golden baselines live in `tests/golden/`
(regenerate with `python tests/golden/record_signals.py` and `python scripts/record_backtest.py`).
Full determinism proof: `python -m pytest -m slow -q`.
## Telegram
/start /status /signals /paper /performance /risk /health, Quick Analyze, Full Analyze, scheduled analysis.

`/signals` is report-only. `/paper` is the explicit paper-execution command and is
restricted to the configured administrator.
## Metrics
`common.metrics` exposes Prometheus counters for signals, orders, equity, exposure. Falls back to no-op payload when prometheus_client is absent.
## Security
Encryption password loads only from `/run/secrets/SECRET_ENCRYPTION_PASSWORD` or
the `SECRET_ENCRYPTION_PASSWORD` environment variable. Never commit `.env`.
## Deployment
`Dockerfile` + `docker-compose.yml` (app + redis). CI runs pytest on Windows with TA-Lib.
## Troubleshooting
No signals: check `last_errors` via /health. Redis missing: caching disabled automatically. ML missing: signal pipeline continues without ML scores.
