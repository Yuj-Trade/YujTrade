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

There is no test suite. Verify changes by running the relevant entrypoint and checking `logs/app.log`.

## Architecture

Entry point `main.py` (`MainApp`) starts the Telegram bot and the scheduled analysis loop. All wiring goes through the composition root:

- `services/trading_service.py` — `create_trading_stack()` is the **only** composition root. Never build the stack anywhere else. Returns `(config_manager, resource_manager, market_data_provider, trading_service)`. Cleanup is the caller's responsibility (`provider.close()`, `service.cleanup()`, `resources.cleanup()`).
- `TradingService` — the quality pipeline, in this exact order: `SignalGenerator` → `MultiTimeframeAnalyzer` (score >= 0.3, no direction conflict) → `_passes_quality_gates` (per-timeframe `min_confidence_threshold` → `min_trend_strength` → `min_volume_surge`) → `SignalRanking` (per-timeframe cap first, then `max_signals_per_run`). Also owns `SignalTracker`.

Layer map:

| Path | Role |
|---|---|
| `data/` | `MarketDataProvider`, `DataValidator`; `data/sources/` fetchers (binance, coingecko, yfinance, alphavantage, cryptopanic, coindesk, defillama, messari, news, marketindices, alternativeme) on `base_fetcher.py` |
| `features/` | `feature_engineering.py`; `features/indicators/` — factory, base, trend, momentum, volatility, volume, cycle, custom, all_indicators |
| `modeling/` | `ModelManager`, model definitions, optuna optimization |
| `models/` | Trained artifacts: `models/lstm/scaler_lstm_<symbol>_<tf>.pkl`, `models/xgboost/xgboost_<symbol>_<tf>.json` (tracked in git) |
| `strategy/` | `signal_generator`, `multi_timeframe`, `signal_ranking`, `signal_tracker` |
| `analysis/` | `market_analyzer`, `correlation`, `scoring` |
| `backtesting/` | Backtest engine |
| `common/` | Domain dataclasses/enums (`core.py`), `constants.py`, cache, exceptions, utils |
| `config/` | `settings.py` (`SecretsManager`, `ConfigManager`), `logger.py` |
| `app/` | `telegram_bot.py` (TelegramBotHandler), `tasks.py` |
| `utils/` | `background_manager` (BackgroundTaskManager), `circuit_breaker`, `resource_manager` (ResourceManager), `security` (KeyEncryptor) |
| `openspec/` | Spec-driven development — see its `AGENTS.md` |

## Coding Conventions

- **Python 3.10+**: modern union syntax (`X | None`), type hints on public functions, dataclasses for domain models (in `common/core.py`).
- **Language**: identifiers, docstrings, and log messages in English. Inline explanatory comments are frequently in Persian (Farsi) — match the surrounding file's mix; don't translate existing comments.
- **Logging**: always `from config.logger import logger` (loguru). Never `print()` or stdlib `logging`. Loguru writes to stdout (INFO) and `logs/app.log` (DEBUG, 10 MB rotation, 7-day retention).
- **Async**: all I/O paths are async. Never call an async function from sync code — e.g. `ResourceManager.get_redis_client()` is async; Redis is connected in `initialize()` (idempotent), not in `__init__`.
- **Windows**: every new entrypoint must set `asyncio.WindowsSelectorEventLoopPolicy()` on `win32` (see bottom of `main.py`). `pywin32` is platform-gated in requirements.txt.
- **Comments referencing gaps**: Persian comments with "شکاف N" numbers document decisions from earlier refactor fixes. Keep them when editing nearby code.

## Rules

- **Secrets**: never hardcode. `.env` (gitignored) holds either plain values or `ENCRYPTED_<KEY>` values that `SecretsManager` decrypts via `KeyEncryptor`. Never commit `.env`; if decryption fails, re-encrypt rather than embedding a fallback.
- **Model data contract**: training and prediction both read data limits ONLY from `ConfigManager` (`model_data_limits`, `model_prediction_limit`). Never hardcode limits.
- **Single composition root**: use `create_trading_stack()`; do not create parallel stack builders or duplicate dependency wiring.
- **Config layering**: defaults live in `ConfigManager.DEFAULT_CONFIG`; runtime overrides in `config.json` (gitignored, generated at runtime). Indicator weights and cache TTLs in `indicator_weights.json` (tracked).
- **`Main/` is a vendored Python environment (venv)**, not project code. Never read, edit, or search it; exclude it from greps/globs. (`.vscode/settings.json` references a stale `./venv/` path — the real venv is `Main/`, activated via `Main/Scripts/Activate.ps1`.)
- **OpenSpec workflow**: open `openspec/AGENTS.md` whenever a request mentions planning, proposals, new capabilities, breaking changes, or architecture. Scaffold proposals under `openspec/changes/<verb-led-kebab-id>/` (`add-`, `update-`, `remove-`, `refactor-`), validate with `openspec validate <id> --strict`, and do not implement until the proposal is approved. Skip proposals for bug fixes, typos, config changes, and non-breaking dependency updates.

## Domain Context

- **Timeframes**: `1h`, `4h`, `1d`, `1w`, `1M` (`common/constants.py:TIME_FRAMES`).
- **Symbols**: loaded from `symbols.txt` (one `BTC/USDT`-style pair per line, deduplicated) into `SYMBOLS`.
- **Thresholds** in `LONG_TERM_CONFIG` (`common/constants.py`): per-timeframe `min_confidence_threshold` (1h: 82 → 1M: 65), `min_risk_reward_ratio` 2.8, `max_signals_per_run` 3, per-timeframe `min_data_points`.
- **Signal lifecycle**: `SIGNAL_EXPIRY_BY_TIMEFRAME` and `DECAY_HALF_LIFE_BY_TIMEFRAME` (hours) in constants; multi-timeframe confirmation pairs/weights in `MULTI_TF_CONFIRMATION_MAP` / `MULTI_TF_CONFIRMATION_WEIGHTS`.
- **Caching**: Redis (Redis Cloud) via `ResourceManager`; TTLs per data category in `ConfigManager.DEFAULT_WEIGHTS_CONFIG["cache_config"]`. Missing `REDIS_TOKEN` disables caching gracefully.

## Git Workflow

- Single `main` branch; commits in short imperative summaries (recent style: "sync progress", "sync complete - start test").
- `copyfile/full-trade.txt` is a generated full-code export that is regenerated (`python copyfile/copy.py`) and committed as part of each sync.
- Always end commit messages with `Co-Authored-By: Claude Code <noreply@anthropic.com>`.
