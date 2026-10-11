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

Current fixtures are synthetic (seed 42) and `signals_baseline.json` is `[]`;
re-recording with real warehouse data is tracked in `docs/open_issues.md`.

## 5. Protected holdout protocol

The final 15% of data is evaluation-only. It never participates in fitting or
optimization, and it is not exercised by routine tests.

```bash
python scripts/run_holdout.py tests/fixtures/ohlcv_1h.csv --confirm
```

- Without `--confirm`: rejected (`PermissionError`).
- A second run with the same data hash is rejected unless `--force-rerun` is
  passed. State lives in `runs/holdout_used.json` (`--state` overrides it).
- Refresh the environment report after a holdout:
  `python scripts/generate_reports.py`.

## 6. Metrics and logs

- Metrics: set `metrics_enabled=true` to serve Prometheus on `127.0.0.1:9108`
  (`METRICS_PORT` overrides the port).
- Set `SENTRY_DSN` to enable Sentry, otherwise no-op.
- Structured logs: `LOG_FORMAT=json`. Loguru writes stdout (INFO) and
  `logs/app.log` (DEBUG, 10 MB rotation, 7-day retention).

## 7. Scheduler recovery

`SchedulerStore` (`runs/scheduler.db`, configurable via `scheduler_db_path`)
records `finished_at` per job. On restart, `is_due()` compares the stored
timestamp against `now`: a missed interval runs immediately (catch-up), it is
never skipped silently. If the DB is deleted, every job is treated as never
run and the next cycle executes on schedule. No manual recovery step exists —
verify via `/health` that the loop resumed.

## 8. Runbook

- Run the bot: `python main.py`. Paper execution is the default.
- Use `/signals` for reporting and `/paper` for an explicit paper order
  (admin only).
- Keep `execution_dry_run=true` until a separately reviewed live deployment.

## 9. Troubleshooting

| Symptom | Action |
|---|---|
| No signals | Check `last_errors` via `/health`; `mtf_data_missing` on thin data is expected |
| Redis missing | Caching disables automatically; no action needed |
| ML missing | Signal pipeline continues without ML scores; check `model_unavailable` log lines |
| `Failed to create encryptor` | Mounted secret and `.env` disagree; rotate per section 2 |
| Stale paper positions | Caller supplied no mark price; equity excludes them until fresh marks arrive |
| Scheduler silent after restart | Check `runs/scheduler.db` readability; verify `/health` |
| Golden mismatch after re-record | Expected only when fixture data changed; otherwise investigate before committing |
