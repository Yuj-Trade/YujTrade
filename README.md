# YujTrade

Long-term crypto trading-signal engine with Telegram delivery. Paper trading
is the default; live execution stays behind an explicit dry-run flag.

## Architecture

```
Market Data -> Validation -> Indicators -> Scoring -> Signal -> MTF ->
Ranking -> Risk -> Portfolio -> Paper/Live -> PnL -> Calibration
```

Layer map:

| Path | Role |
|---|---|
| `domain/` | Pure decision logic, stdlib only (`outcome`, `sizing`, `levels`, `gates`, `types`, `signal_id`). No I/O, no dependencies on other layers. Import contract enforced by `tests/unit/test_architecture.py`. |
| `application/` | Orchestration over `domain` only (`decide.py`, `snapshot.py`). |
| `data/` | `MarketDataProvider`, `DataValidator`; `data/sources/` fetchers (binance, coingecko, yfinance, alphavantage, cryptopanic, coindesk, defillama, messari, news, marketindices, alternativeme) on `base_fetcher.py`. |
| `features/` | `feature_engineering.py`; `features/indicators/` (trend, momentum, volatility, volume, cycle, custom). |
| `modeling/` | `ModelManager`, model definitions (`models.py`), artifact registry (`artifacts.py`), optuna optimization (`optimization.py`). |
| `backtesting/` | Deterministic event-loop simulator (`simulator.py`, entry at next open, stop-first, gap-aware exits), `WalkForwardValidator` + `HoldoutGuard` (`walk_forward.py`), Monte Carlo (`montecarlo.py`), causal `historical_signals.py`. |
| `trading/` | Paper execution (`paper_trading.py`, `execution.py`, `orders.py`), risk (`risk_manager.py`, `margin.py`), append-only paper ledger (`ledger.py`, unique `signal_id`). |
| `strategy/` | `signal_generator`, `multi_timeframe`, `signal_ranking`, `signal_tracker` (ML calibration lives here). |
| `analysis/` | `market_analyzer`, `correlation`, `scoring`. |
| `services/` | `trading_service.py` — `create_trading_stack()` is the only composition root. |
| `common/` | Shared models (`core.py`), `constants.py` (timeframes, symbols, `LONG_TERM_CONFIG`), cache, exceptions, utils. |
| `config/` | `settings.py` (`SecretsManager`, `ConfigManager`), `logger.py` (loguru). |
| `app/` | `telegram_bot.py` (TelegramBotHandler), `tasks.py`. |
| `utils/` | `background_manager`, `circuit_breaker`, `resource_manager`, `security` (`KeyEncryptor`), `scheduler_store`. |
| `scripts/` | Operator entry points (see Commands). |
| `tests/` | 725 default-gate tests plus slow golden/holdout tests (`tests/golden/`). |

## Installation

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux (bash):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Verify the gate before anything else:

```bash
python -m pytest -m "not slow and not ml" -q
```

## Configuration

Create a `.env` file in the repo root (there is no `.env.example`; never
commit `.env`). Keys are read plaintext or as `ENCRYPTED_<KEY>` values
decrypted via `KeyEncryptor` (see `scripts/encrypt_keys.py`):

| Key | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token (required to run) |
| `ADMIN_CHAT_ID` | Admin chat allowed to use `/paper` and control commands |
| `SECRET_ENCRYPTION_PASSWORD` | Password for `ENCRYPTED_*` values; also read from `/run/secrets/SECRET_ENCRYPTION_PASSWORD` in Docker |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_TOKEN` | Redis cache; unset token disables caching gracefully |
| `REDIS_SSL` / `REDIS_USERNAME` | `REDIS_SSL=true` selects `rediss://` (TLS); Redis Cloud ports that terminate plain RESP must use `false`. `REDIS_USERNAME` defaults to `default` |
| `REDIS_URL` | Full connection URL that overrides the assembled parts above |
| `CRYPTOPANIC_KEY`, `ALPHA_VANTAGE_KEY`, `COINGECKO_KEY`, `COINDESK_API_KEY`, `MESSARI_API_KEY` | Optional provider keys (features degrade without them) |
| `SENTRY_DSN` | Optional error reporting |

`ConfigManager.DEFAULT_CONFIG` (`config/settings.py`):

| Key | Default | Meaning |
|---|---|---|
| `symbols` / `timeframes` | from `symbols.txt` / `1h 4h 1d 1w 1M` | Universe |
| `signal_threshold` | `10` | Minimum score to emit a signal |
| `max_signals_per_timeframe` | `1` | Cap per timeframe per run |
| `enable_scheduled_analysis` | `false` | Scheduled loop off unless enabled |
| `schedule_hour` | `"*/1"` | `"*/N"` = every N hours, plain number = hour |
| `app_version` | `"6.0.0"` | App version |
| `model_data_limits` | `1h:2000, 4h:1500, 1d:1000, 1w:500, 1M:300` | Single contract for training AND prediction data windows |
| `model_prediction_limit` | `300` | Rows used for one prediction |
| `model_auto_train_on_predict` | `false` | Prediction never trains implicitly |
| `metrics_enabled` / `METRICS_PORT` | `false` / `9108` | Prometheus on `127.0.0.1:9108` when enabled |
| `scheduler_db_path` | `runs/scheduler.db` | SQLite job-run ledger |
| `execution_dry_run` | `true` | Read via `config_manager.get("execution_dry_run", True)`; keep `true` until a separately reviewed live deployment |
| `outcome_notifications_mode` | `"off"` | `off`, `shadow` (record without sending) or `live` (send to the admin) |
| `outcome_notifications_since` | `""` | ISO instant with timezone; required for every mode other than `off`, only the signals created at or after it are notified |
| `outcome_notification_kinds` | `["target", "stop", "expired"]` | The event kinds that are notified |
| `outcome_notification_timeframes` | `[]` | The timeframes that are notified; empty means every supported timeframe |
| `outcome_watch_interval_minutes` | `15` | How often the watch loop runs |
| `outcome_notification_max_attempts` | `3` | Delivery attempts before the notification is abandoned |
| `outcome_claim_ttl_seconds` | `300` | How long a claimed notification stays claimed before it can be claimed again |
| `outcome_watch_concurrency` | `4` | How many symbol and timeframe groups are observed at the same time |

Runtime overrides live in `config.json` (untracked, created at runtime).
Indicator weights live in `indicator_weights.json` (tracked).

## Signal outcome notifications

The bot can tell the administrator that a signal reached its take-profit,
its stop-loss or its expiry. The feature is **off by default**.

- `outcome_notifications_mode` decides what happens: `off` disables it
  completely, `shadow` records the events and the state transitions without
  sending anything, `live` sends the message to the admin chat.
- `outcome_notifications_since` is the lower bound. Every mode other than
  `off` needs it, and it must be an ISO instant with a timezone, for
  example `2026-10-20T00:00:00+00:00`. Only the signals created at or
  after that instant are notified, so a fresh installation cannot replay
  the whole history.
- The notification delay is the duration of the candle plus the watch
  interval: a target that is touched inside a one-hour candle is reported
  after the candle closes, and the watch loop then picks it up within
  `outcome_watch_interval_minutes`.
- The notification is **notify-only**. It never changes the outcome of a
  signal, never writes to the paper ledger and never changes the
  performance report.
- An invalid configuration disables the feature and is logged; it never
  stops the bot.

See `docs/runbook.md` for the daily checks and
`docs/adr/ADR-0010-signal-outcome-notifications.md` for the decisions.

## Commands

| Command | Flags | Notes |
|---|---|---|
| `python main.py` | none | Run the bot + scheduled loop; missing bot credentials exit with code 2 after cleanup |
| `python scripts/train_models.py` | none | Train all models, all symbols x timeframes (network); retrains legacy pickle-scalers to validated JSON |
| `python scripts/encrypt_keys.py` | none | Encrypt `.env` secrets to `ENCRYPTED_*` |
| `python scripts/run_holdout.py <csv>` | `--symbol`, `--timeframe`, `--state PATH` (default `runs/holdout_used.json`), `--out PATH`, `--confirm`, `--force-rerun`, `--with-ml` | Strategy-level protected holdout on a local CSV; writes a full metrics report; never fetches |
| `python scripts/generate_reports.py` | `--output PATH` (default `runs/environment-baseline.json`) | Environment report |
| `python scripts/record_backtest.py` | none | Re-record backtest golden baseline |
| `python tests/golden/record_signals.py` | none | Re-record signals golden baseline |
| `python -m pytest -m "not slow and not ml" -q` | — | Default gate (298 tests) |
| `python -m pytest -m slow -q` | — | Determinism proof (byte-identical goldens) |
| `ruff check .` / `ruff format --check .` | — | Lint + format gates (must be zero) |
| `mypy domain` | — | Strict types on the pure core |

`/signals` is report-only. `/paper` is the explicit paper-execution command
and is restricted to the configured administrator.

## Paper trading and risk

Default mode is paper via `TradingService.execute_signal(signal, mode="paper")`.
Risk model: fixed fractional + volatility cap + Kelly ceiling, portfolio
exposure limits, daily/weekly/drawdown halts (`LONG_TERM_CONFIG` in
`common/constants.py`: per-timeframe `min_confidence_threshold`, `min_risk_reward_ratio`
2.8, `max_signals_per_run` 3).

## Quality gates

`build_gate_config` (`application/gate_config.py`) builds the single gate
used by both the generator and the service. Rejected signals return `None`;
invalid stop/target geometry is rejected before the quality checks.

| Key | Source | Meaning |
|---|---|---|
| `min_confidence_threshold` | `LONG_TERM_CONFIG` per timeframe (1h: 82, 4h: 78, 1d: 72, 1w: 68, 1M: 65) | Minimum 0-100 confidence |
| `min_trend_strength` | `LONG_TERM_CONFIG` (`MODERATE`) | Minimum trend strength rank |
| `min_volume_surge` | `LONG_TERM_CONFIG` (1.4) | Minimum volume ratio |

Threshold values are frozen: shape data to pass them, never lower them.

## Backtest

`EventDrivenSimulator` (`backtesting/simulator.py`) resolves every exit through
`domain.outcome.resolve_outcome` — the same function the live path uses
(parity covered by `tests/unit/trading/test_ledger_parity.py`).
`WalkForwardValidator.split` validates across chronological windows with purge
(`label_horizon`) and embargo (`max(warmup_bars, sequence_length)`); the final
15% is guarded by `HoldoutGuard` and runnable only via `scripts/run_holdout.py
--confirm`. Golden baselines live in `tests/golden/`.

## Metrics and security

`common.metrics` exposes Prometheus counters (signals, orders, equity,
exposure) and falls back to no-op when `prometheus_client` is absent. Serve
with `metrics_enabled=true` (`127.0.0.1:9108`).

Encryption password loads only from `/run/secrets/SECRET_ENCRYPTION_PASSWORD`
or the `SECRET_ENCRYPTION_PASSWORD` environment variable. Rotate by replacing
that value and re-running `scripts/encrypt_keys.py`. Never commit `.env`,
`secret.salt`, `*.db`, `*.pkl`, `*.keras`, `calibration.json`,
`signal_history.json`, or anything under `runs/`, `artifacts/`, `models/`.

## Deployment

`Dockerfile` (pinned `python:3.13-slim-bookworm`, non-root `appuser`,
`HEALTHCHECK` via `scripts/docker_healthcheck.py`) installs the pinned
`requirements.lock`. CI (`.github/workflows/ci.yml`) runs ruff, ruff format
check, mypy on `domain`, the default test gate, a `domain` coverage gate
(>=90%), and a Docker build.

## Troubleshooting

| Symptom | Check |
|---|---|
| No signals | `last_errors` via `/health`; thin data yields `mtf_data_missing` rejections by design |
| Redis missing | Caching disables automatically; bot keeps running |
| ML missing/untrained | Pipeline continues without ML scores; predict returns `model_unavailable`, never trains implicitly |
| Stale paper positions | `snapshot_equity` marks positions `stale` when the caller supplies no mark price; equity excludes them |
| Golden mismatch | Fixtures are synthetic (`scripts/create_fixtures.py`, seed 42); re-record only with real warehouse data (see `docs/open_issues.md`) |
