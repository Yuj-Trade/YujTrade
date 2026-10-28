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
- Provider behavior keys added by the 2026-10-22 app.log remediation. All three
  live in `ConfigManager.DEFAULT_CONFIG` and are overridden in the untracked
  `config.json`:
  - `coingecko_api_tier` (default `"demo"`): `demo` uses the public host
    `api.coingecko.com` with the key sent as the `x_cg_demo_api_key` query
    parameter; `pro` uses `pro-api.coingecko.com` with the `x-cg-pro-api-key`
    header. Any other value raises `ConfigurationError` at construction.
  - `messari_asset_slugs` (default absent): ticker-to-Messari-slug map. Not
    populated because no slug could be verified (see open issues).
  - `coindesk_news_enabled` (default `False`): CoinDesk news is skipped entirely
    unless this is `true`. `api.coindesk.com` does not resolve.

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

## 11. Signal outcome notifications

### The job in the scheduler store

The watch loop records its runs in `runs/scheduler.db` under the job name
`outcome_watch`, next to the `scheduled_analysis` job. The row holds the
scheduled, the started and the finished instant, the status (`success` or
`failed`) and the error text. A `failed` row means the tick raised; the
notification state of the affected signals is untouched, so the next tick
retries them.

### The notification states

The state of a signal lives in `signal_history.json`, in the details of the
signal.

| State | Meaning |
|---|---|
| `pending` | the event is recorded and the message was not delivered yet |
| `claimed` | a delivery is in flight; the claim expires after `outcome_claim_ttl_seconds` |
| `sent` | the message was delivered |
| `shadowed` | the event was recorded but the mode is `shadow`, so nothing was sent |
| `suppressed` | the event does not match the configured kinds, timeframes or lower bound |
| `abandoned` | the delivery failed permanently or the attempt limit was reached |

A `pending` or `claimed` entry is protected: the pruning and the rotation
never remove it. A terminal entry can be pruned after the TTL and can be
rotated away.

### Checking one signal

```bash
python -c "import json;d=json.load(open('signal_history.json'));\
print(json.dumps(d['<signal_id>'], indent=2))"
```

The details carry `outcome_event`, `outcome_event_at`,
`outcome_event_price`, `notification_state`, `notification_attempts` and,
while the delivery is in flight, `notification_claimed_at`.

### Rollback

1. Set `outcome_notifications_mode` to `off` in `config.json`.
2. Restart the bot: `python main.py`.
3. The watch loop no longer starts, so no message is sent. The state stays
   in `signal_history.json` and no migration is needed.
4. A `pending` notification is delivered again at the next activation,
   unless a new `outcome_notifications_since` excludes it.

### Troubleshooting

| Symptom | Action |
|---|---|
| No notification arrives | check the mode, the `outcome_notifications_since` bound and the `notification_state` of the signal; the notification delay is the candle duration plus the watch interval |
| `Outcome notifications disabled` in the log | the configuration is invalid; the feature is off until it is fixed |
| `outcome_watch` job is `failed` | read the error column of the row in `runs/scheduler.db` |
| A message arrives twice | at-least-once delivery: the process died between the send and the completion, the claim TTL bounds the window |
| A signal stays `pending` | the delivery keeps failing; the attempts counter shows the progress and the notification is abandoned at the limit |

## 12. Exchange connectivity

Exchange connectivity is disabled by default. `exchange_enabled` is empty,
`exchange_sandbox` is true, `exchange_shadow_mode` is true and
`exchange_live_enabled` is false in `ConfigManager.DEFAULT_CONFIG`. Nothing in
this section is executed by the agent; the steps marked **operator** run on the
operator machine, with network access to the venues.

See `docs/adr/ADR-0011-exchange-connectivity.md` for the venue registry
decisions and `docs/adr/ADR-0012-exchange-access-profiles.md` for the access
profiles. The outstanding operator work is tracked in
`docs/operator_pending.md`.

### 12.1 Secret names

The repository `.env` carries the exchange key names with empty values. Only
the names are tracked in this document; values are never written here.

Live names: `<PREFIX>_API_KEY`, `<PREFIX>_API_SECRET`, and
`<PREFIX>_API_PASSPHRASE` when the venue needs a passphrase.

Sandbox names: `<PREFIX>_SANDBOX_API_KEY`, `<PREFIX>_SANDBOX_API_SECRET`, and
`<PREFIX>_SANDBOX_API_PASSPHRASE` when the venue needs a passphrase.

`<PREFIX>` is the upper-case `exchange_id` (`BINANCE`, `LBANK`, `CRYPTOCOM`,
`OURBIT`, ...). `python -c "from trading.exchanges.registry import
all_secret_names; print('\n'.join(all_secret_names()))"` prints the full list.

`trading/exchanges/credentials.py` reads only `ENCRYPTED_<NAME>`. A plaintext
value in `.env` makes the credentials unavailable and is reported by name only;
it never silently works and its value never reaches a log.

### 12.2 Startup order

1. **operator** Fill the sandbox or read-only key values in `.env`, then run
   `python scripts/encrypt_keys.py`. The script replaces each plaintext line
   with `ENCRYPTED_<NAME>`.
2. **operator** Run the read-only probe on the operator machine:
   `python scripts/probe_exchanges.py`. It writes `runs/exchange_probe.json`
   and never sends an order. Record the result in
   `docs/exchange_probe_results.md`.
3. **operator** Verify key permissions. When the venue documents a permission
   endpoint, the check runs automatically before a live submission; otherwise
   the human attestation is the only evidence.
4. **operator** Fill `exchange_attested_keys` in `config.json` with the venues
   whose keys were confirmed to carry no withdrawal right.
5. **operator** Enable the venue in `exchange_enabled` and keep
   `exchange_shadow_mode` true. Run the 14-day shadow soak (section 12.6).
6. **operator** Only after the soak passes, set `exchange_shadow_mode` false,
   fill `exchange_live_review_id` with the accepted ADR id, set
   `exchange_sandbox` false, set `execution_dry_run` false and set
   `exchange_live_enabled` true. The live mode additionally needs the
   one-time code from `/exchange_confirm`.

### 12.3 Emergency stop

1. Send `/exchange_halt`. The control row `halted=1` in
   `runs/live_ledger.db` refuses every new submission, including shadow rows.
   Open orders are **not** cancelled by the halt; cancel them at the venue.
2. Run `/exchange_status <client_order_id>` for every row in `pending_submit`
   or `unknown`.
3. Any `unknown` row is a manual decision. Reconciliation reads the venue and
   never re-sends.
4. Resume with `/exchange_resume` only after every unresolved row is closed.

### 12.4 Key rotation

Every 90 days, or immediately after an incident:

1. Create the new key at the venue.
2. Revoke the old key at the venue.
3. Replace the value in `.env`, then run `python scripts/encrypt_keys.py`.
4. Restart the bot and repeat the attestation step: update
   `exchange_attested_keys` in `config.json`.

### 12.5 Backups

- `secret.salt` must be kept offline, outside the repository and outside this
  machine. If it is lost, every `ENCRYPTED_` value is undecryptable and every
  key must be entered again. Losing it does not expose a value; it destroys
  access.
- `runs/live_ledger.db` is copied daily. Run `PRAGMA wal_checkpoint(TRUNCATE)`
  before the copy so the WAL is folded into the main file, then copy the
  `.db` file.

### 12.6 Shadow soak

The soak runs for 14 days with `exchange_shadow_mode` true and
`exchange_enabled` set to the venue. Each signal is recorded as a `shadow` row
and no order is placed. Generate the report with
`python scripts/exchange_shadow_report.py`.

Exit criteria, from `ADR-0011`:

- zero `exchange_not_ready` rows;
- zero `key_not_attested` rows;
- no price deviation outside `exchange_max_price_deviation_pct`;
- no unexplained `unknown` row.

### 12.7 Terms of use and account

This section records the operator statement; it is not a finding of the
application.

> 2026-10-29, operator: I have reviewed the terms of use of my accounts for
> the venues I use.

The application does not verify the operator's identity, residence, or the
sanction regime that applies to an account, and it implements no proxy, VPN, IP
rotation or header workaround. Matching an account to a venue's terms of use
and to applicable sanctions is the operator's responsibility. The `iran`
profile selects the reachable venue set (`lbank`, `ourbit`); it does not
assert that an account is eligible.

## 13. Troubleshooting

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
| CoinGecko `error_code":10011` ("use api.coingecko.com for Demo key") | Set `coingecko_api_tier` to `demo` (public host, `x_cg_demo_api_key` param) or `pro` (pro host, `x-cg-pro-api-key` header) in `config.json`; default is `demo` |
| Cloudflare 403 from CryptoPanic | The network is blocked by Cloudflare. `UpstreamUnavailableError` now counts toward the circuit breaker, so repeated calls stop instead of retrying every cycle. Confirm provider access from this network (U6) |
| `Connection timeout` to `fapi.binance.com` | Network or regional reachability to Binance futures. Spot on `api.binance.com` is unaffected. Test with `Invoke-WebRequest https://fapi.binance.com/fapi/v1/ping -TimeoutSec 10` (U3) |
| `getaddrinfo failed` for Redis | The configured `REDIS_HOST` does not resolve. Check the host in `.env` against the Redis Cloud dashboard (U2). Caching stays disabled until it resolves |
| `[SSL: WRONG_VERSION_NUMBER]` for Redis | `REDIS_SSL` is true but the endpoint terminates plain RESP. Set `REDIS_SSL=false` for ports that are not TLS (Redis Cloud exposes both; the `rediss://` port is usually the one ending in a different last digit) |
| `Redis GET failed: Too many connections` / `No connection available` | The pool is exhausted or the server rejected the client count. Tune `REDIS_MAX_CONNECTIONS` and `REDIS_POOL_TIMEOUT`; cache operations degrade to a miss and never fail a fetch, so this is a warning, not an outage |
| `database is locked` | Should not recur: `IndicatorHistoryWarehouse` now uses WAL, a 30 s busy timeout, and a per-instance `asyncio.Lock`. If it returns, check for another process holding `runs/indicator_history.db` |
| `getaddrinfo failed` for `api.coindesk.com` | The host does not resolve (verified 2026-10-23). CoinDesk news is off by default via `coindesk_news_enabled`; leave it off unless the host resolves |
| `Protocol not found` from `api.llama.fi` | The chain TVL endpoint is `/v2/chains`, not `/tvl/chains` |
| Messari 404 on every asset | `data.messari.io` returned 404 for the API root as well as every asset slug on 2026-10-23. Treat as an unavailable provider, not a slug bug |
