# Operations runbook

1. Copy `.env.example` to `.env` and set `SECRET_ENCRYPTION_PASSWORD`.
   Never commit `.env`, `secret.salt`, `*.db`, `*.pkl`, `*.keras`,
   `calibration.json` or `signal_history.json`.
2. Gate before deployment: `python -m pytest -m "not slow and not ml" -q`.
3. Lint the migration scope: `python -m ruff check domain tests`.
   Type-check the core: `python -m mypy domain`.
4. Train models explicitly with `python scripts/train_models.py`
   (network access; trains every configured symbol/timeframe).
   Prediction never trains implicitly (`model_auto_train_on_predict=false`).
5. Regenerate golden baselines (fixture-only, no network):
   `python tests/golden/record_signals.py`, then
   `python scripts/record_backtest.py`. Both must be byte-identical
   across consecutive runs; proof: `python -m pytest -m slow -q`.
6. Protected holdout (local CSV only, never fetches):
   `python scripts/run_holdout.py tests/fixtures/ohlcv_1h.csv --confirm`
   Rerun with the same data hash is rejected unless `--force-rerun` is passed.
   State lives in `runs/holdout_used.json` (use `--state` to override).
7. Refresh the environment report: `python scripts/generate_reports.py`
   (writes `runs/environment-baseline.json`).
8. Run the bot with `python main.py`; paper execution remains the default.
9. Use `/signals` for reporting and `/paper` for an explicit paper order.
10. Keep `execution_dry_run=True` until a separately reviewed live deployment.
11. Metrics: set `metrics_enabled=true` to serve Prometheus on
    `127.0.0.1:9108`; set `SENTRY_DSN` to enable Sentry, otherwise no-op.
    Structured logs: `LOG_FORMAT=json`.
