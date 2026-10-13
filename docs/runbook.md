# Operations runbook

## 1. Pre-deployment gate

```bash
ruff check . && ruff format --check .
mypy domain
python -m pytest -m "not slow and not ml" -q
python -m pytest -m "not slow and not ml" -q --cov=domain --cov-fail-under=90
git status --porcelain   # must be empty
```

## 2. Secrets

- Create `.env` in the repo root (never commit it). Required: `TELEGRAM_BOT_TOKEN`,
  `ADMIN_CHAT_ID`. Optional providers degrade gracefully when absent.
- `SECRET_ENCRYPTION_PASSWORD` is read from `/run/secrets/SECRET_ENCRYPTION_PASSWORD`
  first, then the environment. Rotation procedure:
  1. Set the new password in the secret store (or env).
  2. Run `python scripts/encrypt_keys.py` to re-encrypt `.env` values.
  3. Restart the bot; watch for `Failed to create encryptor` in logs — it means
     the mounted secret and `.env` values disagree.
- Denylist (never commit): `.env`, `secret.salt`, `*.db`, `*.pkl`, `*.keras`,
  `calibration.json`, `signal_history.json`, `runs/`, `artifacts/`, `models/`.

## 3. Training and prediction contract

- Train explicitly: `python scripts/train_models.py` (network access; all
  configured symbols x timeframes).
- Prediction never trains implicitly (`model_auto_train_on_predict=false`).
  A missing or untrained artifact yields the explicit `model_unavailable`
  event and the ML score component degrades to zero — the analysis continues.
- Model data windows come only from `ConfigManager` (`model_data_limits`,
  `model_prediction_limit`).
- Scalers persist as validated `scaler.json` (no pickle). Artifacts written
  before this change (legacy `scaler_*.pkl`) never load: retrain every model
  with `python scripts/train_models.py` before expecting predictions.

## 4. Golden baselines

Fixture-only, no network:

```bash
python tests/golden/record_signals.py
python scripts/record_backtest.py
```

Both files must be byte-identical across consecutive runs. Proof:

```bash
python -m pytest -m slow -q
```

Current fixtures are deterministic (fixed end date, seeded `default_rng`,
regime-shaped trends) and the golden baselines are non-trivial (51 signals,
15 trades). Re-recording with real warehouse data stays user-side.

## 5. Protected holdout protocol

The final 15% of data is evaluation-only. It never participates in fitting or
optimization, and it is not exercised by routine tests.

```bash
python scripts/run_holdout.py tests/fixtures/ohlcv_1h.csv --confirm
python scripts/run_holdout.py data.csv --symbol BTC/USDT --timeframe 1h --confirm --out runs/manual/holdout_report.json
```

- Without `--confirm`: rejected (`PermissionError`).
- A second run with the same data hash is rejected unless `--force-rerun` is
  passed. State lives in `runs/holdout_used.json` (`--state` overrides it).
- The report (`--out`, default `runs/<run_id>/holdout_report.json`) holds
  rows, data/config hashes, trades count, win rate, profit factor, max
  drawdown, Sharpe, final equity, buy-and-hold return, rejection counts, a
  bootstrap confidence interval, git commit and evaluation time.
- `--with-ml` is refused unless every current ML artifact's `data_end`
  predates the holdout window (no-leak rule).
- Refresh the environment report after a holdout:
  `python scripts/generate_reports.py`.

## 6. Startup contract

Missing `TELEGRAM_BOT_TOKEN` or `ADMIN_CHAT_ID` ends the run with exit code
2 after cleanup. The bot never idles silently with credentials absent.

## 7. Metrics and logs

- Metrics: set `metrics_enabled=true` to serve Prometheus on `127.0.0.1:9108`
  (`METRICS_PORT` overrides the port).
- Set `SENTRY_DSN` to enable Sentry, otherwise no-op.
- Structured logs: `LOG_FORMAT=json`. Loguru writes stdout (INFO) and
  `logs/app.log` (DEBUG, 10 MB rotation, 7-day retention).

## 8. Scheduler recovery

`SchedulerStore` (`runs/scheduler.db`, configurable via `scheduler_db_path`)
records `finished_at` per job. On restart, `is_due()` compares the stored
timestamp against `now`: a missed interval runs immediately (catch-up), it is
never skipped silently. If the DB is deleted, every job is treated as never
run and the next cycle executes on schedule. No manual recovery step exists —
verify via `/health` that the loop resumed.

## 9. Runbook

- Run the bot: `python main.py`. Paper execution is the default.
- Use `/signals` for reporting and `/paper` for an explicit paper order
  (admin only).
- Keep `execution_dry_run=true` until a separately reviewed live deployment.

## 10. Troubleshooting

| Symptom | Action |
|---|---|
| No signals | Check `last_errors` via `/health`; `mtf_data_missing` on thin data is expected |
| Redis missing | Caching disables automatically; no action needed |
| ML missing | Signal pipeline continues without ML scores; check `model_unavailable` log lines |
| `Failed to create encryptor` | Mounted secret and `.env` disagree; rotate per section 2 |
| Stale paper positions | Caller supplied no mark price; equity excludes them until fresh marks arrive |
| Scheduler silent after restart | Check `runs/scheduler.db` readability; verify `/health` |
| Golden mismatch after re-record | Expected only when fixture data changed; otherwise investigate before committing |
