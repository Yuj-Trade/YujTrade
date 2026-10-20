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
- Training writes to a staging directory and the artifact registry copies the
  staged files into the new version. The promoted version is never rewritten
  in place, so its recorded hashes stay valid.

### 3.1 Drift check (no training, no network)

```bash
python scripts/train_models.py --dry-run --data tests/fixtures/drift_stable_1h.csv \
  --symbol BTC/USDT --timeframe 1h --report runs/drift_report.json
```

- Exit code `0` = no drift, `2` = drift detected, `1` = failure.
- `--data` points the run at a local CSV; without it the check needs network
  access. The CI job uses committed fixtures only.
- A feature whose window holds fewer than `drift_min_window` effective
  samples is reported as `insufficient_data` and never counted as drift.
- The live window is timeframe-aware (`drift_live_windows` in
  `ConfigManager`); the family-wise error rate is `drift_alpha`.

### 3.2 Guarded retraining

```bash
python scripts/train_models.py --report runs/training_report.json
python scripts/train_models.py --warm-start --only-on-drift
```

- Every retrained candidate is compared against the currently promoted model.
  A candidate that loses directional accuracy or degrades RMSE beyond the
  configured bound is **not** promoted; the promoted pointer and its files
  stay exactly as they were, and the rejected version is kept for forensics.
- `--warm-start` continues from the promoted artifact (weights and scaler).
  The scaler is never refitted on that path, because a continued model must
  see the feature space it was trained in.
- `--no-rollback-guard` promotes without the comparison. Use it only for an
  operator-driven recovery; the run logs a warning.
- `--artifact-root` writes a separate artifact tree (useful for a rehearsal
  that must not touch the live pointer).

### 3.3 Walk-forward validation

```bash
python scripts/run_walk_forward.py tests/fixtures/walk_forward_1h.csv \
  --symbol BTC/USDT --timeframe 1h --folds 4 --out runs/walk_forward_report.json
```

- The report carries per-fold hygiene, per-fold metrics, a `metrics_hash` for
  run-over-run comparison and a `leakage_flags` counter that must be `0`.
- The command exits non-zero on any leakage flag or non-finite metric.
- Real-data walk-forward runs stay user-side; the committed fixture proves the
  harness, not the strategy.

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

## 10. Paper performance report

### Reading the report

- In Telegram: `/performance` (admin only). It shows the tracker summary
  plus the trade count, the status, the profit factor, the expectancy,
  the total return, the maximum drawdown, the Sharpe and Sortino ratios,
  the `no_data` count and the first eight characters of the `data_hash`.
- As a file:
  `python scripts/generate_performance_report.py --as-of 2026-10-20T12:00:00+00:00`
  writes `runs/performance/performance-report.json` and prints the
  `data_hash`. The same data and configuration always produce the same
  hash; a changed hash means the data or a parameter changed.
- The full definitions and the arithmetic: `docs/performance-worked-example.md`
  and `docs/adr/ADR-0009-performance-metrics.md`.

### Configuration keys

| Key | Default | Meaning |
|---|---|---|
| `performance_ledger_enabled` | `false` | write every resolution to the ledger |
| `paper_fee_rate` | `0.001` | fee rate of the paper engine and of the report cost |
| `paper_slippage_rate` | `0.0005` | slippage rate of the paper engine and of the report cost |
| `performance_rf_annual` | `0` | annual risk-free rate of the Sharpe and Sortino ratios |
| `performance_periods_per_year` | `365` | annualisation factor |
| `performance_min_trades_for_ratios` | `30` | below this the status is `insufficient_sample` |
| `risk_per_trade_pct` | `1.0` | fixed fraction risked per trade |
| `initial_cash` | `10000.0` | starting equity of the report |

The keys live in `ConfigManager.DEFAULT_CONFIG`. `performance_ledger_enabled`
stays `false` in the committed defaults and is turned on in the local
`config.json` only after the fourteen-day soak.

### Daily controls

1. Check `/health` and the reconciliation log line
   `Reconciled N expired pending signal(s).`
2. Check the `no_data` ratio in the report. Above 5 % the reconciliation
   cadence is too coarse for the expiry window: the resolver asks for
   `ceil(expiry / candle_duration) + 2` candles and marks the rest
   `no_data`.
3. Compare the ledger and the tracker with
   `python scripts/compare_ledger_and_tracker.py`. The number of new
   tracker resolutions must equal the number of new ledger rows plus the
   recorded `no_data` rows. The acceptance checklist is
   `docs/soak-checklist.md`.
4. The ledger is append-only: `UPDATE` and `DELETE` on
   `signal_resolutions` raise. Never prune it, and never delete the
   database to "clean up"; a deletion destroys the audit trail.
5. Two runs of the report script over the same data must print the same
   `data_hash`.

## 11. Troubleshooting

| Symptom | Action |
|---|---|
| No signals | Check `last_errors` via `/health`; `mtf_data_missing` on thin data is expected |
| Redis missing | Caching disables automatically; no action needed |
| ML missing | Signal pipeline continues without ML scores; check `model_unavailable` log lines |
| `Failed to create encryptor` | Mounted secret and `.env` disagree; rotate per section 2 |
| Stale paper positions | Caller supplied no mark price; equity excludes them until fresh marks arrive |
| Scheduler silent after restart | Check `runs/scheduler.db` readability; verify `/health` |
| Golden mismatch after re-record | Expected only when fixture data changed; otherwise investigate before committing |
| Podman TLS timeouts on pull/build | MTU blackhole in the podman-machine network: `podman machine ssh -- "sudo -n ip link set eth0 mtu 1280"` (runtime-only, repeat after machine restart) |
