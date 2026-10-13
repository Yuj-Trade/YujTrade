# CLAUDE.md

Guidance for AI assistants working in this repository.

## Project Overview

YujTrade — an asynchronous Python crypto trading-signal bot. Fetches market data from multiple sources, computes technical indicators, runs LSTM + XGBoost models per symbol/timeframe, and delivers ranked trading signals to an admin via a Telegram bot. App version is tracked in `ConfigManager.DEFAULT_CONFIG["app_version"]`.

## Commands

```bash
python main.py                    # Run the bot (async; sets WindowsSelectorEventLoopPolicy on win32)
python scripts/train_models.py    # Train all models (all symbols x timeframes)
python scripts/encrypt_keys.py    # Encrypt secrets in .env
python copyfile/copy.py           # Regenerate copyfile/full-trade.txt (full code export)
```

OpenSpec (spec-driven development):

```bash
openspec list                     # Active changes
openspec list --specs             # Existing capabilities
openspec validate <change-id> --strict
openspec archive <change-id> --yes
```

There is a 298-test default suite. Verify changes with the gates below, never by
eyeballing entrypoints alone:

```bash
python -m pytest -m "not slow and not ml" -q   # default gate
ruff check . && ruff format --check .           # must be zero
mypy domain                                     # strict types on the pure core
python -m pytest -m "not slow and not ml" -q --cov=domain --cov-fail-under=90
```

Golden baselines (`tests/golden/`) must be byte-identical across runs;
`python -m pytest -m slow -q` proves determinism. Check `logs/app.log`
only for runtime behavior, not as a substitute for tests.

## Architecture

Entry point `main.py` (`MainApp`) starts the Telegram bot and the scheduled analysis loop. All wiring goes through the composition root:

- `services/trading_service.py` — `create_trading_stack()` is the **only** composition root. Never build the stack anywhere else. Returns `(config_manager, resource_manager, market_data_provider, trading_service)`. Cleanup is the caller's responsibility (`provider.close()`, `service.cleanup()`, `resources.cleanup()`).
- `TradingService` — the quality pipeline, in this exact order: `SignalGenerator` → `MultiTimeframeAnalyzer` (score >= 0.3, no direction conflict) → `_passes_quality_gates` (per-timeframe `min_confidence_threshold` → `min_trend_strength` → `min_volume_surge`) → `SignalRanking` (per-timeframe cap first, then `max_signals_per_run`). Also owns `SignalTracker`.

Layer map:

| Path | Role |
|---|---|
| `domain/` | Pure decision logic, stdlib only (`outcome`, `sizing`, `levels`, `gates`, `types`, `signal_id`). Import contract enforced by `tests/unit/test_architecture.py`. |
| `application/` | Orchestration over `domain` only (`decide.py`, `snapshot.py`, `gate_config.py`) |
| `data/` | `MarketDataProvider`, `DataValidator`; `data/sources/` fetchers (binance, coingecko, yfinance, alphavantage, cryptopanic, coindesk, defillama, messari, news, marketindices, alternativeme) on `base_fetcher.py` |
| `features/` | `feature_engineering.py`; `features/indicators/` — factory, base, trend, momentum, volatility, volume, cycle, custom, all_indicators |
| `modeling/` | `ModelManager`, model definitions, `ArtifactRegistry` (`artifacts/`) with mandatory verified metadata, JSON scalers (`scaler_io.py`, never pickle), optuna optimization |
| `backtesting/` | `EventDrivenSimulator` (resolves via `domain.outcome`), `WalkForwardValidator` + `HoldoutGuard`, Monte Carlo, causal `historical_signals.py` |
| `trading/` | Paper execution, risk, append-only `PaperLedger` (unique `signal_id`) |
| `strategy/` | `signal_generator`, `multi_timeframe`, `signal_ranking`, `signal_tracker` |
| `analysis/` | `market_analyzer`, `correlation`, `scoring` |
| `common/` | Shared models (`core.py`), `constants.py`, cache, exceptions, utils |
| `config/` | `settings.py` (`SecretsManager`, `ConfigManager`), `logger.py` |
| `app/` | `telegram_bot.py` (TelegramBotHandler), `tasks.py` |
| `utils/` | `background_manager` (BackgroundTaskManager), `circuit_breaker`, `resource_manager` (ResourceManager), `security` (KeyEncryptor) |
| `openspec/` | Spec-driven development — see its `AGENTS.md` |

## Coding Conventions

- **Python 3.13**: `requires-python = ">=3.13,<3.14"`; modern union syntax (`X | None`), type hints on public functions, dataclasses for domain models (in `common/core.py`).
- **Language**: identifiers and log messages in English. Production code carries zero comments and zero docstrings (enforced by `tests/unit/test_no_comments.py`); rationale lives in `docs/`. Tool pragmas (`noqa`, `type:`, `pragma`) are the only allowed exceptions.
- **Logging**: always `from config.logger import logger` (loguru). Never `print()` or stdlib `logging`. Loguru writes to stdout (INFO) and `logs/app.log` (DEBUG, 10 MB rotation, 7-day retention).
- **Async**: all I/O paths are async. Never call an async function from sync code — e.g. `ResourceManager.get_redis_client()` is async; Redis is connected in `initialize()` (idempotent), not in `__init__`.
- **Windows**: every new entrypoint must set `asyncio.WindowsSelectorEventLoopPolicy()` on `win32` (see bottom of `main.py`). `pywin32` is platform-gated in requirements.txt.
- **Comments**: forbidden in production code, including gap markers;
  record decisions in `docs/` (ADRs, `open_issues.md`, `docs/architecture.md`) instead.

## Rules

- **Secrets**: never hardcode. `.env` (gitignored) holds either plain values or `ENCRYPTED_<KEY>` values that `SecretsManager` decrypts via `KeyEncryptor`. Never commit `.env`; if decryption fails, re-encrypt rather than embedding a fallback.
- **Model data contract**: training and prediction both read data limits ONLY from `ConfigManager` (`model_data_limits`, `model_prediction_limit`). Never hardcode limits.
- **Single composition root**: use `create_trading_stack()`; do not create parallel stack builders or duplicate dependency wiring.
- **Config layering**: defaults live in `ConfigManager.DEFAULT_CONFIG`; runtime overrides in `config.json` (gitignored, generated at runtime). Indicator weights and cache TTLs in `indicator_weights.json` (tracked).
- **Artifact policy**: trained models live in the `ArtifactRegistry`
  (`artifacts/<symbol>/<timeframe>/<model_type>/`, pointer `current.json`).
  Every version carries mandatory verified metadata (`data_start`,
  `data_end`, `feature_list`, `params`, `git_commit`, `library_versions`,
  `files_sha256`); loads verify hashes and a mismatch is
  `model_unavailable`, never a crash. Scalers persist as validated JSON;
  legacy `scaler_*.pkl` files never load. `models/` on disk is untracked
  legacy output — never re-track it, never depend on it in new code.
  Prediction never trains (`model_auto_train_on_predict=false`).
- **Startup contract**: missing `TELEGRAM_BOT_TOKEN` or `ADMIN_CHAT_ID` ends
  the run with exit code 2 after cleanup. Never idle with the bot off.
- **Gate contract**: `build_gate_config` (`application/gate_config.py`) is
  the single gate constructor for generator and service; rejected signals
  return `None` (never a `TradingSignal`). Threshold values in
  `LONG_TERM_CONFIG` are frozen — shape data, not thresholds.
- **`Main/` is a vendored Python environment (venv)**, not project code. Never read, edit, or search it; exclude it from greps/globs. (`.vscode/settings.json` references a stale `./venv/` path — the real venv is `Main/`, activated via `Main/Scripts/Activate.ps1`.)
- **OpenSpec workflow**: open `openspec/AGENTS.md` whenever a request mentions planning, proposals, new capabilities, breaking changes, or architecture. Scaffold proposals under `openspec/changes/<verb-led-kebab-id>/` (`add-`, `update-`, `remove-`, `refactor-`), validate with `openspec validate <id> --strict`, and do not implement until the proposal is approved. Skip proposals for bug fixes, typos, config changes, and non-breaking dependency updates.

## Domain Context

- **Timeframes**: `1h`, `4h`, `1d`, `1w`, `1M` (`common/constants.py:TIME_FRAMES`).
- **Symbols**: loaded from `symbols.txt` (one `BTC/USDT`-style pair per line, deduplicated) into `SYMBOLS`.
- **Thresholds** in `LONG_TERM_CONFIG` (`common/constants.py`): per-timeframe `min_confidence_threshold` (1h: 82 → 1M: 65), `min_risk_reward_ratio` 2.8, `max_signals_per_run` 3, per-timeframe `min_data_points`.
- **Signal lifecycle**: `SIGNAL_EXPIRY_BY_TIMEFRAME` and `DECAY_HALF_LIFE_BY_TIMEFRAME` (hours) in constants; multi-timeframe confirmation pairs/weights in `MULTI_TF_CONFIRMATION_MAP` / `MULTI_TF_CONFIRMATION_WEIGHTS`.
- **Caching**: Redis (Redis Cloud) via `ResourceManager`; TTLs per data category in `ConfigManager.DEFAULT_WEIGHTS_CONFIG["cache_config"]`. Missing `REDIS_TOKEN` disables caching gracefully.

## Git Workflow

- Single `main` branch. One concern per commit; messages name the concern
  (`chore:`, `fix:`, `test:`, `style:`, `docs:`, `build:`, `ci:`). A commit
  that changes runtime behavior carries a `[behavior-change]` tag and its
  tests.
- Pre-commit gate for every commit: full default pytest gate green plus
  `sha256sum tests/golden/*.json` unchanged (unless the commit IS a
  golden re-record with real data).
- `copyfile/full-trade.txt` is gitignored; regenerate locally with
  `python copyfile/copy.py` when a full review bundle is needed.
