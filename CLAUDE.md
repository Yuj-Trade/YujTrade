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

## Repository map

The repository is organized by responsibility rather than by framework:

| Area | Important files and responsibilities |
|---|---|
| Entry and composition | `main.py` starts the async application, installs signal handlers, starts Telegram/scheduling, and performs shutdown; `services/trading_service.py:create_trading_stack()` is the only dependency composition root |
| Pure decision core | `domain/types.py`, `gates.py`, `levels.py`, `outcome.py`, `sizing.py`, and `signal_id.py`; standard library only and no I/O |
| Application orchestration | `application/decide.py`, `snapshot.py`, and `gate_config.py`; coordinates domain decisions without owning infrastructure |
| Market data | `data/data_provider.py`, `data/data_validator.py`, `data/source_health.py`, `data/warehouse.py`, and `data/sources/*_fetcher.py`; all provider/network paths are async |
| Features | `features/feature_engineering.py` and `features/indicators/`; indicator construction is centralized in `factory.py` |
| Analysis and strategy | `analysis/market_analyzer.py`, `scoring.py`, `correlation.py`; `strategy/signal_generator.py`, `multi_timeframe.py`, `signal_ranking.py`, and `signal_tracker.py` |
| Modeling | `modeling/model_manager.py`, `models.py`, `artifacts.py`, `scaler_io.py`, and `optimization.py`; artifact metadata and hashes are part of the load contract |
| Backtesting | `backtesting/simulator.py`, `walk_forward.py`, `montecarlo.py`, and `historical_signals.py`; historical paths must remain causal and deterministic |
| Trading | `trading/execution.py`, `paper_trading.py`, `orders.py`, `risk_manager.py`, `margin.py`, `portfolio.py`, and append-only `ledger.py` |
| Runtime support | `config/settings.py`, `config/logger.py`, `common/*`, and `utils/*` for configuration, logging, caching, resources, scheduling, resilience, and encryption |
| Telegram application | `app/telegram_bot.py` and `app/tasks.py`; administrator-only commands include report-only `/signals` and explicit `/paper` execution |
| Operations and checks | `scripts/*`, `Dockerfile`, `.github/workflows/ci.yml`, `tests/`, `docs/`, and `openspec/` |

Do not infer package ownership from a convenient import. Keep the dependency
direction `domain` <- `application` <- infrastructure/application packages;
`tests/unit/test_architecture.py` is the executable enforcement point.

## Runtime flow and ownership

1. `main.py` awaits `create_trading_stack()` and owns the returned resources.
2. `MarketDataProvider` gathers source data, validates it, and feeds market
   regime detection and feature generation.
3. The scoring path applies regime-based weight adjustments before producing a
   candidate signal.
4. `SignalGenerator` creates candidates, `MultiTimeframeAnalyzer` requires
   sufficient confirmation without direction conflict, and `TradingService`
   applies per-timeframe gates.
5. `SignalRanking` applies the per-timeframe cap before the global
   `max_signals_per_run` cap. `SignalTracker` owns lifecycle/decay tracking.
6. `/signals` reports results. `/paper` is the explicit paper execution path;
   execution remains dry-run by default and risk checks must remain in force.
7. Shutdown must stop Telegram polling, cancel background tasks, close the
   scheduler store, clean the trading service, close the market provider, and
   clean resources.

Healthy rejection is represented by `None` and is distinct from an analysis
failure. Invalid data, unavailable required inputs, and computation failures
must retain their exception/logging semantics instead of becoming a silent
no-signal result.

## Configuration and data contracts

- `ConfigManager.DEFAULT_CONFIG` in `config/settings.py` is the default source.
  `config.json` is an untracked runtime override; `indicator_weights.json` is
  tracked configuration. Do not duplicate defaults in services or scripts.
- `symbols.txt` defines the deduplicated `BTC/USDT`-style universe. Supported
  timeframes are `1h`, `4h`, `1d`, `1w`, and `1M`.
- Training and prediction must both use `model_data_limits` and
  `model_prediction_limit` from `ConfigManager`. Prediction never trains
  implicitly.
- Artifacts are addressed under
  `artifacts/<symbol>/<timeframe>/<model_type>/` through `ArtifactRegistry`.
  Each version requires verified data bounds, feature list, parameters, git
  commit, library versions, and file SHA-256 metadata. Hash mismatch produces
  `model_unavailable`, not a crash. Scalers are validated JSON; legacy pickle
  scalers never load.
- `PaperLedger` is append-only and uses unique `signal_id` values. Signal
  outcome resolution must be shared by live/paper and backtest paths.
- Redis is optional. A missing `REDIS_TOKEN` disables caching gracefully; it
  must not become a reason to add synchronous I/O to an async path.

## Test and fixture layout

Use the parallel `tests/` tree for all tests:

- `tests/unit/` covers architecture, startup, domain, services, strategy,
  trading, configuration, and utility contracts.
- `tests/integration/` covers cross-package behavior and external boundaries.
- `tests/golden/` contains deterministic JSON baselines and their recorders;
  do not re-record them for convenience.
- `tests/fixtures/`, `tests/mocks/`, and `tests/helpers/` contain shared test
  inputs and doubles. Keep tests isolated and use the existing async fixtures.

The normal validation sequence is the default pytest gate, Ruff check and
format check, and strict mypy for `domain`. Add coverage and golden/slow
checks for changes touching the pure core, deterministic simulation, signals,
or model/backtest contracts. CI additionally runs dependency audit, secrets
guard, and a Docker healthcheck/build.

## Files an agent must treat as generated or sensitive

Never read secrets into a response or commit them. `.env`, `secret.salt`,
`*.db`, `*.pkl`, `*.keras`, `calibration.json`, `signal_history.json`,
`config.json`, `runs/`, `artifacts/`, `models/`, `logs/`, `Main/`, and
`__pycache__/` are not source-of-truth application files. `copyfile/` and
`skills/` are excluded from packaging and are not to be modified for ordinary
feature work. `copyfile/full-trade.txt` is a local review export and is
gitignored.

## Documentation and change discipline

- Put architectural rationale in `docs/architecture.md` or an ADR under
  `docs/adr/`; put known limitations in `docs/open_issues.md` and operational
  procedures in `docs/runbook.md`.
- Requests for new capabilities, breaking changes, architecture work, or
  proposals must follow `openspec/AGENTS.md` before implementation. Bug fixes,
  typo fixes, configuration changes, and non-breaking dependency updates do
  not require a proposal.
- Keep production code free of explanatory comments/docstrings according to
  the repository tests; document rationale here or in `docs/` instead.
- Prefer one concern per commit with `docs:`, `fix:`, `test:`, `style:`,
  `build:`, or `ci:` prefixes. Runtime behavior changes require the
  `[behavior-change]` tag and corresponding tests. Do not amend or rewrite
  existing commits unless explicitly requested.
