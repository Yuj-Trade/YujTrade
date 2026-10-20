# YujTrade Engineering Improvement Plan

**From Production-Ready v0.4.0 to Institutional Grade — a verified, phased implementation roadmap**

| Document Control | |
|---|---|
| Version | 3.0 (supersedes v2.0 checklist report) |
| Date | 2026-10-19 |
| Baseline | Tag `v0.4.0-production-ready` → HEAD `fa37bc9` |
| Scope | All runtime packages, `scripts/`, `tests/`, CI, and documentation |
| Verification standard | Every claim in this document is backed by a reproducible command in §12 |
| Change discipline | `openspec/AGENTS.md` governs all capability work; CLAUDE.md rules apply throughout |
| Current focus | **Phase 4 — Production Operations & Security (next)** |

---

## 1. Executive Summary

YujTrade is an asynchronous, spec-driven crypto trading-signal system with a strictly layered architecture (`domain` ← `application` ← infrastructure), a single composition root (`services/trading_service.py:create_trading_stack()`), deterministic golden baselines, and verified model artifacts with SHA-256 integrity.

**Verified baseline at v0.4.0:**

| Dimension | State | Evidence |
|---|---|---|
| Tests | ~330 collected, default suite green; 100% `domain` coverage gate | `python -m pytest -m "not slow and not ml" -q` |
| Lint & types | Zero ruff findings; `ruff format --check` clean; `mypy domain` clean | §12 gate block |
| Golden determinism | 59 signals / 15 trades, byte-stable; hermetic recorder resets warehouse state | `python -m pytest -m slow -q`; `signals_baseline.json` / `backtest_baseline.json` |
| Security posture | Zero pickle, zero secrets in git, zero bare `except:`, 159 audited exception sites | `docs/exceptions_audit.md`, CI `secrets-guard` job |
| Container | Podman image builds, digest-pinned base, non-root `appuser`, in-container healthcheck exit 0 | `Dockerfile`, `scripts/docker_healthcheck.py` |
| Model integrity | `ArtifactRegistry` enforces metadata + SHA-256 on load; mismatch → `model_unavailable` | `modeling/artifacts.py`, ADR series |

**The gap to close.** The system is *correct* but not yet *self-improving*: SQLite I/O is not uniformly async, signal calibration state is unbounded and unpersisted, model retraining lacks drift detection and automated rollback, observability is fragmented, the dependency lock is hash-less (blocked on platform), and alpha research (multi-asset risk, regime templates, event-driven signals) is designed but unwired.

**Plan of record.** Six phases over ~14 calendar weeks (parallelizable after Phase 3), each with explicit work items, file-level ownership, acceptance criteria, exit gates, and a risk register. Items marked **[P]** require an approved OpenSpec proposal before implementation, per repository policy. Items marked **[B]** change runtime behavior and require the `[behavior-change]` commit tag plus accompanying tests. Frozen contracts (`LONG_TERM_CONFIG` thresholds, paper-only execution, exit-code-2 startup, gate centralization via `application/gate_config.py`) are never modified by this plan.

**Delivered so far.** Phases 0 to 3 are complete and verified locally: the configuration contradiction is resolved and tested (Phase 0), blocking I/O is gone from the async paths and network fetches are deduplicated per run (Phase 1), the signal lifecycle is bounded, persisted, idempotent and observable (Phase 2), and the model lifecycle is now closed — drift is detected statistically, retraining can continue from the promoted artifact, and a degraded candidate can no longer replace a good one (Phase 3). What remains is deployment hardening (Phase 4), portfolio-level alpha research (Phase 5) and institutional auditability (Phase 6).

---

## 2. Delivery Dashboard

| Phase | Title | Weeks | Status | Exit gate | Evidence |
|---|---|---|---|---|---|
| 0 | Hygiene & Configuration Truth | 1 | ✅ **Delivered** | ✅ Passed | `3e07c6c`, `98bcc57` — config untracked + golden-independence test, `backtrader` removed, dead code purged |
| 1 | Architecture & I/O Discipline | 2–3 | ✅ **Delivered** | ✅ Passed | `10de3ed` (PaperLedger → `aiosqlite` + hygiene guard), `337f212` (run-scoped fetch memoization) |
| 2 | Signal Quality, Calibration & Observability | 2 | ✅ **Delivered** | ✅ Passed | `227304e` (bounded history + persisted adaptive thresholds), `33d0d91` (correlation IDs + lifecycle metrics), `fa37bc9` (metric primitives) |
| 3 | Model Lifecycle & Data Robustness | 3 | ✅ **Delivered** | ✅ Passed | §8 — drift detection, warm start, guarded promotion, feature trace, holdout Monte Carlo, walk-forward job, `model-quality` workflow |
| 4 | Production Operations & Security | 2 | ⏳ Planned | ⏳ Pending | §9 |
| 5 | Alpha & Portfolio Research | 4 | ⏳ Planned | ⏳ Pending | §10 |
| 6 | Institutional Readiness | ongoing | ⏳ Planned | ⏳ Pending | §11 |

**Frozen contracts — never modified by any phase.** `LONG_TERM_CONFIG` threshold values and indicator formulas; paper-only execution (`execution_dry_run` default `True`); startup failure with exit code 2 on missing Telegram credentials; single gate constructor (`application/gate_config.py:build_gate_config()`); single composition root (`services/trading_service.py:create_trading_stack()`); stdlib-only `domain/` package.

---

## 3. Current State Assessment

### 3.1 Strengths to preserve

1. **Layered purity.** `domain/` is stdlib-only, enforced by `tests/unit/test_architecture.py`. All new logic in this plan respects the import direction `domain` ← `application` ← infrastructure.
2. **Single composition root.** `create_trading_stack()` is the only wiring point; caller-owned cleanup (`provider.close()`, `service.cleanup()`, `resources.cleanup()`).
3. **Signal pipeline order is contractual:** `SignalGenerator` → `MultiTimeframeAnalyzer` (score ≥ 0.3, no direction conflict) → per-timeframe quality gates → `SignalRanking` (per-TF cap, then global cap). Gate construction flows only through `application/gate_config.py:build_gate_config()`.
4. **Artifact policy.** Mandatory verified metadata (`data_start`, `data_end`, `feature_list`, `params`, `git_commit`, `library_versions`, `files_sha256`); JSON scalers only; prediction never trains.
5. **Determinism.** Golden JSON baselines with SHA-256 pre-commit checks; holdout paths causal and isolated from live external/ML data.

### 3.2 Verified gaps (evidence-confirmed, not assumed)

| # | Gap | Evidence | Phase | State |
|---|---|---|---|---|
| G1 | `config.json` tracked while `.gitignore:194` lists it, and golden baselines depend on its `signal_threshold: 10` | `git ls-files config.json`; `git check-ignore` | 0 | ✅ Resolved |
| G2 | `backtrader` declared in `requirements.txt`, absent from prod imports and from `requirements.lock` | requirements scan | 0 | ✅ Resolved |
| G3 | `PaperLedger` performs blocking `sqlite3` I/O on async paths | `trading/ledger.py` | 1 | ✅ Resolved |
| G4 | `get_fundamental_data` / `get_onchain_data` hit the network once per symbol×timeframe (~5×/run) when Redis is absent | `data/sources/` call-graph | 1 | ✅ Resolved |
| G5 | `signal_history.json` calibration store has no TTL, rotation, or size bound | `strategy/signal_tracker.py` | 2 | ✅ Resolved |
| G6 | `AdaptiveThresholdManager` state is in-memory only — calibration lost on restart | `strategy/` | 2 | ✅ Resolved |
| G7 | No correlation IDs, partial metrics wiring, no tracing spans across the signal lifecycle | `common/metrics.py` audit | 2 | ✅ Resolved (spans remain Phase 4 opt-in) |
| G8 | Retraining has no drift detection, no warm-start, no automated OOS-degradation rollback | `scripts/train_models.py` | 3 | ✅ Resolved |
| G9 | `requirements.lock` is hash-less; Windows-built hashes would be wrong-platform | `docs/open_issues.md` | 4 | ⏳ Open (platform-blocked) |
| G10 | `ENCRYPTION_PASSWORD` not yet migrated to `SECRET_ENCRYPTION_PASSWORD`; no documented rotation procedure | `utils/security.py`, runbook | 4 | ⏳ Open (user-side) |
| G11 | Missed scheduler runs are caught up silently — no repeated-miss alerting | `utils/scheduler_store.py` | 4 | ⏳ Open |
| G12 | Position sizing is per-symbol only; no cross-asset correlation risk; allocation is fixed-fractional | `trading/risk_manager.py`, `domain/sizing.py` | 5 | ⏳ Open |
| G13 | `ExchangeAdapter` abstraction absent (Binance-only data path); single-process scaling ceiling | `data/sources/binance_fetcher.py` | 6 | ⏳ Open |

### 3.3 Delivered work — Phase 0 to Phase 2 (verification recap)

**Phase 0 — Hygiene & Configuration Truth**

- `config.json` untracked while remaining on disk; `.gitignore` entry intact. `signal_threshold: 10` is the explicit `ConfigManager.DEFAULT_CONFIG` default, so golden output no longer depends on a mutable file. Guarded by `tests/unit/common/test_config_json_independence.py` (defaults identical with and without the legacy override) and `tests/unit/scripts/test_dead_code_guard.py::test_config_json_stays_untracked`.
- `backtrader` removed from `requirements.txt`; importer-absence enforced by `tests/unit/scripts/test_dead_code_guard.py::test_backtrader_neither_declared_nor_imported`.
- Dead code purged: `scripts/run_golden.py`, `scripts/install_mock.py`, `symtemp.txt`, four caller-less fetcher methods — each with repo-wide zero-reference proof.
- Stale documentation purged (`BacktestingEngine` prose); naive datetime replaced with `datetime.now(UTC)`; README test count corrected.

**Phase 1 — Architecture & I/O Discipline**

- `PaperLedger` migrated from blocking `sqlite3` to `aiosqlite`; the append-only contract and the unique `signal_id` constraint are preserved verbatim. `record_fill` / `resolve_outcome` are `async`; callers updated at the composition root only. Event-loop hygiene guard proves no `sqlite3` import is reachable from `create_trading_stack()`.
- Run-scoped external-data memoization: `get_fundamental_data` / `get_onchain_data` / `get_macro_data` / `get_trending_data` / `get_all_indices` collapse to one upstream call per `(key, scope)` per analysis cycle. The memo is cleared at cycle end and is **not** a TTL cache — Redis TTL semantics are unchanged. A counting-fake test proves ≤ 1 upstream call per datum per cycle.

**Phase 2 — Signal Quality, Calibration & Observability**

- `signal_history.json` is TTL-bounded and rotates to `signal_history.<n>.json` past a size cap; `AdaptiveThresholdManager` state is persisted and restored across restarts with schema versioning. A corrupt file degrades to fresh state with a warning — never a crash, mirroring the artifact policy.
- Adaptive values adjust **ranking confidence only**; the frozen per-timeframe `min_confidence_threshold` acceptance gates are untouched, and an immutability test pins `LONG_TERM_CONFIG` byte-for-byte.
- Run-scoped idempotency: replaying an analysis cycle yields one tracker record and one ledger row.
- Observability spine: `run_id` / `signal_id` correlation IDs bound through loguru, plus lifecycle counters for candidates, per-gate rejections, emitted signals, expiry resolutions, and artifact hash mismatches.

---

## 4. Guiding Principles (binding for every phase)

1. **Proposals before capabilities.** Any new capability, breaking change, or architecture work follows `openspec/AGENTS.md`: scaffold under `openspec/changes/<verb-led-kebab-id>/`, `openspec validate <id> --strict`, implement only after approval.
2. **Frozen contracts.** `LONG_TERM_CONFIG` thresholds and indicator formulas are frozen (shape data only). Paper execution is the default; nothing in this plan lowers quality gates or enables live execution.
3. **No hardcoded policy.** Thresholds, TTLs, data limits, drift parameters, and model bounds come from `ConfigManager` / existing helpers — never literals.
4. **Zero comments, loguru logging, async everywhere, Python 3.13 syntax.** Rationale lives in `docs/` and ADRs, not in code.
5. **One concern per commit.** Prefixes `chore:`/`fix:`/`test:`/`style:`/`docs:`/`build:`/`ci:`; `[behavior-change]` tag when runtime behavior changes; golden SHA-256 unchanged unless the commit *is* a golden re-record with real data.
6. **Tests are the only proof.** Logs never substitute for tests; the smallest relevant test runs first, then the full default gate.
7. **Degrade, never crash.** Every new runtime surface (calibration state, artifact metadata, drift reports, trace files) follows the artifact policy: unreadable or corrupt input produces a warning plus a safe default, never an unhandled exception on a live path.

---

## 5. Phase 0 — Hygiene & Configuration Truth ✅ Delivered

**Objective:** eliminate every contradiction between what the repository *says* and what it *is*. Zero risk, high trust impact.

### 5.1 The `config.json` contradiction — resolved

Decision: **Option A (untrack)**. `signal_threshold: 10` is the explicit default in `ConfigManager.DEFAULT_CONFIG` (`config/settings.py`); `config.json` stays on disk as a runtime override and out of the index. Golden independence is proven by test, not by convention.

### 5.2 Dependency hygiene — resolved

| ID | Task | Detail | Status |
|---|---|---|---|
| 0.2.1 | Pin `aiosqlite` | `aiosqlite==0.22.1` present in `requirements.lock` | ✅ Done |
| 0.2.2 | Remove `backtrader` | Deleted from `requirements.txt`; importer-absence test added | ✅ Done |
| 0.2.3 | Hash-pinned lock prep | Blocked on G9; tracked under Phase 4.4 | Phase 4 |

### 5.3 Dead-code verification — completed and guarded

- [x] `scripts/run_golden.py` removed (duplicate of `tests/golden/record_signals.py`, hardcoded `C:/ME/YujTrade` path)
- [x] `scripts/install_mock.py` removed (pandas_ta mock, zero importers)
- [x] `symtemp.txt` removed (stale 208-byte symbol list)
- [x] Four caller-less fetcher methods removed (`get_exchange_info`, `get_all_futures_symbols`, `get_circulating_supply`, `get_all_assets`)
- [x] `backtrader` importer-absence check added to `tests/unit/scripts/test_dead_code_guard.py`

### 5.4 Stale documentation & naive datetime — completed

- [x] `BacktestingEngine` references purged from test prose
- [x] README test count corrected
- [x] `app/telegram_bot.py` display string now timezone-aware UTC

**Phase 0 exit gate:** ✅ default pytest green · ruff/mypy clean · golden SHA-256 unchanged · a passing test asserts the resolved `config.json` state · no undeclared dependency in `requirements.txt`.

---

## 6. Phase 1 — Architecture & I/O Discipline ✅ Delivered

**Objective:** zero blocking I/O on the event loop, one network fetch per unique datum per run, and a dependency set that tells the truth.

### 6.1 Async-SQLite migration — complete

| Store | State | Action |
|---|---|---|
| `IndicatorHistoryWarehouse` | ✅ `aiosqlite`; measured 174 ms → 23 ms per cycle | Regression-test the bound |
| `SchedulerStore` | ✅ `aiosqlite` | None |
| `PaperLedger` | ✅ `aiosqlite` (Phase 1) | Append-only contract and unique `signal_id` preserved verbatim |

Delivered behavior contract: every write path (`record_fill`, `resolve_outcome`) is `async`; a concurrency test proves two coroutines appending distinct `signal_id` values under `asyncio.gather` produce two rows in deterministic file order; an event-loop hygiene test proves no `sqlite3` import remains on any path reachable from `create_trading_stack()`.

### 6.2 Run-level fetch memoization — delivered [B]

Design as implemented:

- A per-analysis-cycle memo keyed by `(key, scope)` lives inside the analysis cycle, cleared at cycle end. It is *not* the Redis cache: TTL semantics are unchanged (`get_cache_ttl()` remains the only TTL source) and the memo only collapses duplicates within a cycle.
- Scope semantics: `fundamental`/`onchain` are per-symbol, `macro`/`trending`/`market_indices` are global, `derivatives`/`order_book` remain per-call because they are order-book state, not static facts.
- Acceptance: a unit test with a counting fake fetcher asserts exactly one upstream call per `(key, scope)` per cycle across all five timeframes.

### 6.3 Remaining audit — complete

- [x] `data/sources/` swept with the dead-code-guard pattern; definition-only methods removed with repo-wide zero-caller proof.
- [x] No path re-introduces integer-literal `ex=` / `cache_ttl` (AST literal guard in `tests/unit/test_cache_ttl_source.py`).

**Phase 1 exit gate:** ✅ event-loop hygiene test green · counting-fetcher test proves ≤ 1 upstream call per datum per cycle · `requirements.txt` contains only imported dependencies · default suite + ruff/mypy green · golden hashes unchanged.

---

## 7. Phase 2 — Signal Quality, Calibration & Observability ✅ Delivered

**Objective:** make the signal lifecycle measurable, bounded, and idempotent — the difference between "signals that work" and "signals you can prove work."

### 7.1 Persist and bound adaptive thresholds — delivered

- **Persistence:** `AdaptiveThresholdManager` state is serialized to `signal_history.json` on shutdown and loaded on startup; the schema is versioned; a corrupt file produces a warning plus fresh state (never a crash).
- **TTL & rotation:** records older than `signal_history_ttl_days` (default 30, from `ConfigManager`) are pruned at write time; a size cap (`signal_history_max_entries`) triggers rotation to `signal_history.<n>.json` with the same gitignore treatment as the primary file.
- **Frozen-threshold guard:** adaptive values adjust *ranking confidence only*. The frozen `LONG_TERM_CONFIG` per-timeframe `min_confidence_threshold` values remain the acceptance gates, and an immutability test asserts `LONG_TERM_CONFIG` is byte-identical to a pinned fixture.

### 7.2 Lifecycle correctness — delivered

- **Expiry reconciliation:** `TradingService.reconcile_pending_signals()` resolves expired signals through `domain/outcome.py` — shared by live, paper, and backtest resolution paths. A test asserts all three paths produce identical outcome records.
- **Idempotency key:** `signal_id` (symbol + tf + timestamp + type) deduplicates, and a run-scoped idempotency wrapper prevents a retried analysis cycle from double-recording in `SignalTracker` or the `PaperLedger`. Replaying the same cycle twice yields one tracker record and one ledger row.
- **Rejection semantics (contract, no change):** healthy rejection is `None` and stays distinct from analysis failure — invalid/unavailable inputs retain their exception semantics rather than collapsing into no-signal.

### 7.3 Observability spine — delivered

1. **Correlation IDs.** `run_id` / `signal_id` are bound via loguru `logger.bind()` at cycle start; every log line in generation → gating → ranking → resolution carries both. A test greps captured logs for the bound pair across one simulated cycle.
2. **Metrics wiring.** Counters in `common/metrics.py` cover: candidates generated, per-gate rejections (gate name as label), signals emitted, expiry resolutions, artifact hash mismatches, and orders executed. Every path in `TradingService` + `SignalTracker` is wired; a unit test asserts counters advance for each lifecycle transition.
3. **Tracing (opt-in, deferred).** OpenTelemetry spans for the pipeline stages, activated by a config flag defaulting to off. **[P]** — infrastructure change; proposal deferred to Phase 4 because it changes deployment surface.

**Phase 2 exit gate:** ✅ restart-persistence test for adaptive state · rotation/TTL test · idempotent-replay test · correlation-ID and metrics-advance tests · default suite + ruff/mypy green · goldens unchanged.

---

## 8. Phase 3 — Model Lifecycle & Data Robustness ✅ Delivered

**Objective:** a closed retraining loop that detects drift, retrains incrementally, and rolls itself back when quality regresses — with no human guesswork.

**Why this phase existed.** Phases 0–2 made the *signal lifecycle* provable. The *model lifecycle* was the remaining ungoverned surface: `scripts/train_models.py` retrained and promoted unconditionally, with no drift signal, no warm-start path, and no guard that stopped a degraded model from replacing a good one. A single bad retrain could therefore silently downgrade live signal quality, and no past decision could be reconstructed after the fact.

### 8.1 Capability map

| ID | Capability | Tag | Files owned | Status |
|---|---|---|---|---|
| 3.1 | Feature-drift detection (two-sample KS per feature) | [B] | `modeling/drift.py` | ✅ Done |
| 3.2 | Warm-start retraining | [B] | `modeling/models.py`, `modeling/model_manager.py` | ✅ Done |
| 3.3 | Automated promotion / rollback on OOS degradation | [B] | `modeling/promotion.py`, `modeling/artifacts.py`, `modeling/model_manager.py` | ✅ Done |
| 3.4 | Training CLI: `--dry-run`, `--warm-start`, fixture mode | [B] | `scripts/train_models.py` | ✅ Done |
| 3.5 | Prediction-time feature trace keyed by `signal_id` | [B] | `strategy/prediction_trace.py`, `strategy/signal_generator.py`, `services/trading_service.py` | ✅ Done |
| 3.6 | Versioned Monte-Carlo bootstrap CI in the holdout report | [B] | `backtesting/montecarlo.py`, `scripts/run_holdout.py` | ✅ Done |
| 3.7 | Walk-forward validation job on deterministic fixtures | — | `scripts/run_walk_forward.py` | ✅ Done |
| 3.8 | Model-quality CI workflow (drift-check + walk-forward + lifecycle) | — | `.github/workflows/model-quality.yml` | ✅ Done |
| 3.9 | Feature store for training reuse | **[P]** | — | ⛔ Deferred behind an OpenSpec proposal |

### 8.2 3.1 — Feature-drift detection

**Contract.** Drift is a *statistical statement about data*, not about model quality. The detector answers: "has the live feature distribution moved away from the distribution the current model was trained on?"

- **Test.** Two-sample Kolmogorov–Smirnov test per feature, reference window (older data) versus live window (most recent data).
- **Implementation.** `modeling/drift.py` implements the KS statistic and the Kolmogorov p-value in pure Python (no `scipy` dependency, no new requirement, fully deterministic). The test is a property of the *data windows*, never of the model.
- **Features.** Drift is measured on stationary derived features — not on raw price levels, where any trending series trivially "drifts": `close_return_1`, `close_return_5`, `volume_return_1`, `intrabar_range`.
- **Dependency-aware sampling.** Multi-bar features overlap, so their samples are autocorrelated and the KS independence assumption would not hold. Each feature is sampled with a stride equal to its dependency length (`close_return_5` uses stride 5), restoring independence at the cost of fewer effective samples. Measured effect: without striding, a stationary window was flagged in 21 of 60 runs; with striding, 2 of 100.
- **Multiple-testing correction.** Four features tested at a nominal 5% would raise a false alarm in roughly 18% of runs. A Bonferroni correction (`alpha / feature_count`) keeps the family-wise error rate at the configured `drift_alpha`. The correction and the effective threshold are reported in every drift summary.
- **P-value construction.** The finite-sample corrected Kolmogorov argument (`en + 0.12 + 0.11/en`) is used, with the complementary (Theta) form for small arguments where the alternating series converges too slowly to truncate safely. The implementation matches the reference distribution to machine precision (max deviation 1.7e-16 over the tested range); an earlier truncation bug that halved p-values was caught by that comparison.
- **Thresholds.** `drift_alpha` (default `0.05`), `drift_min_window` (default `100` effective samples) and the per-timeframe live windows (`drift_live_windows`, default `drift_live_window`) come from `ConfigManager` — never literals.
- **Degradation.** A window with fewer than `drift_min_window` effective samples yields `status="insufficient_data"`, `drifted=False` — absence of evidence never becomes a false alarm.
- **Output.** `DriftReport` records (feature, KS statistic, p-value, drifted, sample counts, status, threshold) and a JSON-serializable summary with a `schema_version`, so drift reports are diffable run-over-run.

**Acceptance.** A shifted fixture flags drift; the matching stationary fixture does not; a truncated window reports `insufficient_data` instead of raising. Enforced by `tests/unit/modeling/test_drift.py` (24 assertions) and by the committed fixture pair `tests/fixtures/drift_stable_1h.csv` / `drift_shifted_1h.csv`.

### 8.3 3.2 — Warm-start retraining

**Contract.** `--warm-start` continues from the currently promoted artifact instead of starting from a random initialization, and the promoted artifact still carries complete metadata plus fresh OOS metrics.

- **Precondition.** The current artifact must exist and pass `ArtifactRegistry.verify_current()`; a hash mismatch is `model_unavailable`, never a silent warm start from a corrupted model.
- **Feature space.** The scaler is **not** refitted during a warm start. The persisted JSON scaler is reloaded and reused, so the continued model sees the same feature space it was trained in. This is the single most common correctness trap in warm-start implementations.
- **Weights.** `XGBoostModel` continues the persisted booster (`xgb_model=` continuation); `LSTMModel` re-creates the network, then restores the persisted weights before the additional epochs. Keras optimizer state is not restored — documented, because optimizer momentum is not part of the artifact contract.
- **Fallback.** When no current artifact exists, `--warm-start` degrades to a cold start and logs it.
- **Outcome.** `ModelManager.train_model` returns a `TrainingOutcome` (version, promotion state, fresh OOS metrics) instead of a bare boolean, so the caller can decide promotion on evidence.
- **Acceptance.** A warm-start run produces a *new* artifact version (never mutates the promoted one), with full metadata and freshly computed OOS metrics.

### 8.4 3.3 — Automated promotion and rollback

**Contract.** A retrained model is promoted only if it is not measurably worse than the model it would replace.

- **Policy.** `modeling/promotion.py` holds a pure, side-effect-free decision function over `(baseline_metrics, candidate_metrics, policy)`:
  - no baseline (first training) → promote;
  - candidate metrics unavailable or NaN → **do not promote** (unknown quality is not acceptable quality);
  - directional accuracy drop greater than `promotion_max_directional_accuracy_drop` → reject;
  - RMSE increase greater than `promotion_max_rmse_increase_ratio` → reject.
- **Bounds.** Both bounds come from `ConfigManager`.
- **Mechanics.** Training always writes a *new* version directory with `update_current=False`. Promotion is a separate, explicit pointer write (`ArtifactRegistry.promote_version()`), so a rejected candidate leaves the promoted pointer exactly where it was. The rejected attempt is logged with its metrics and reason, and the version directory is retained for forensics.
- **Write isolation (bug fixed in this phase).** A model resolves its file paths from its own `model_path`, and the manager points that path at the promoted artifact directory so the model can be loaded from it. Left alone, `fit()` saved the new weights *into the promoted version directory*, invalidating its recorded `files_sha256` and making the promoted artifact fail its own integrity check on the next load — which would have made the rollback guarantee nominal rather than real. Training now writes to a staging directory and the registry copies the staged files into the new version. A candidate that is not promoted is also evicted from the in-memory cache, so the next prediction reloads the promoted artifact instead of silently using the rejected weights. Enforced by `tests/unit/modeling/test_training_isolation.py`.
- **Failure isolation.** A promotion that cannot complete (missing version, unwritable pointer) is reported as `status="error"` on that entry and never aborts the remaining models.
- **Acceptance.** A fixture with poisoned data never promotes; a healthy retrain promotes; a missing baseline promotes; a NaN candidate never promotes. Enforced by `tests/unit/modeling/test_promotion.py` and `tests/unit/scripts/test_train_models_lifecycle.py`.

### 8.5 3.4 — Training CLI

`scripts/train_models.py` now exposes a real command-line surface:

| Flag | Effect |
|---|---|
| `--dry-run` | Drift check only. No training, no artifact writes, no promotion. Exit code `0` when no drift, `2` when drift is detected. |
| `--warm-start` | Continues from the currently promoted artifact (see 8.3). |
| `--data <csv>` | Reads OHLCV from a local CSV instead of the network — the deterministic fixture mode used by CI. |
| `--symbol` / `--timeframe` | Scope the run to one symbol/timeframe. |
| `--only-on-drift` | Retrain only where drift is detected. |
| `--no-rollback-guard` | Explicit opt-out of the promotion guard for operator-driven recoveries; logs loudly. |
| `--report <path>` | Writes the JSON run report (drift summary + per-model promotion decisions). |
| `--artifact-root <path>` | Points the run at a different artifact root. |

Network training remains user-side per `docs/runbook.md`; the agent never runs network training.

### 8.6 3.5 — Prediction-time feature trace

**Contract.** For every emitted signal, the exact feature schema and values the model saw are persisted, keyed by `signal_id`, so any past decision can be reconstructed.

- **Location.** `strategy/prediction_trace.py`; runtime data under `runs/feature_vectors/<signal_id>.json` (gitignored, same treatment as `signal_history.json`).
- **Payload.** `schema_version`, `signal_id`, `symbol`, `timeframe`, `timestamp`, `feature_names` (ordered), `feature_values`, `ml_predictions`, `threshold_used`, `score`.
- **Injection.** The recorder is an optional constructor dependency of `SignalGenerator` (`None` → no-op). It is wired by `TradingService` only when `prediction_trace_enabled` is true (default `false`), so the golden recorder path and the deterministic test path are unaffected.
- **Serialization safety.** Non-finite floats become `null` and unknown objects become strings, so every trace file is strict, parseable JSON.
- **Degradation.** An unwritable target produces a warning; the signal is still emitted. Trace persistence never blocks a signal.
- **Out of scope.** A *feature store* usable for training reuse is **[P]** and stays deferred until an OpenSpec proposal is approved.

### 8.7 3.6 — Versioned Monte-Carlo block in the holdout report

**Contract.** Distributional robustness is diffable run-over-run.

- `backtesting/montecarlo.py` gains a versioned bootstrap block: `{"schema_version", "confidence", "simulations", "seed", "samples", "ci_low", "ci_high", "mean"}`, computed with a fixed seed so the same trade set always yields the same interval.
- `scripts/run_holdout.py` appends it to the report under the `monte_carlo` key. The pre-existing `bootstrap_ci_95` field is retained for compatibility.
- The report remains deterministic: same input, same block, byte-for-byte.
- The candle/signal/metric helpers shared by the holdout and walk-forward scripts moved into `backtesting/historical_signals.py` so the two reports cannot drift apart.

### 8.8 3.7 / 3.8 — Walk-forward job and CI workflow

- `scripts/run_walk_forward.py` splits a deterministic fixture with `WalkForwardValidator`, evaluates each fold causally (each bar sees only its own prefix), and emits a versioned JSON report containing per-fold hygiene (train/test sizes, overlap, embargo gap), per-fold metrics, a `metrics_hash` for run-over-run comparison, and an explicit `leakage_flags` counter that must be `0`.
- `.github/workflows/model-quality.yml` adds three jobs on a weekly schedule plus manual dispatch:
  - **drift-check** — the stationary fixture must report no drift (exit `0`), and the shifted fixture must report drift (exit `2`). Both outcomes are asserted, so the detector itself is proven in CI, not just the data.
  - **walk-forward** — `python scripts/run_walk_forward.py --data tests/fixtures/walk_forward_1h.csv`; the job fails on any leakage flag or non-finite metric.
  - **model-lifecycle** — the Phase 3 contract tests as a dedicated, fast job.
- The workflow never trains on the network and never promotes an artifact.

### 8.9 Phase 3 exit gate

- [x] Drift fixture flags a shifted distribution; an unchanged distribution does not; a short window reports `insufficient_data`.
- [x] Promotion policy tests: poisoned data never promotes; healthy retrain promotes; NaN candidate never promotes.
- [x] Trainer tests: `--dry-run` writes no artifact and no pointer; a degraded candidate leaves the promoted pointer unchanged; a healthy candidate updates it.
- [x] Warm-start test: the promoted artifact is untouched and a new version is produced.
- [x] Prediction-trace test: a trace file is written per `signal_id`; disabling the feature writes nothing; a write failure degrades to a warning.
- [x] Holdout report contains the versioned `monte_carlo` block and stays byte-deterministic.
- [x] Walk-forward runner reports zero leakage flags on fixtures and is deterministic across runs.
- [x] `python -m pytest -m "not slow and not ml" -q` green (444 passed) · `ruff check .` · `ruff format --check .` · `mypy domain` green · `domain` coverage 100%.
- [x] Golden SHA-256 unchanged (`tests/golden/*.json`).
- [x] ADR for the model-lifecycle decisions merged under `docs/adr/ADR-0008-model-lifecycle.md`.
- [ ] Golden *re-recording* is not reproducible on every workstation — a pre-existing, environment-dependent condition (TensorFlow oneDNN float ordering), verified to fail on a clean checkout of `main` as well. Tracked with its evidence in `docs/open_issues.md`; the committed baseline was not overwritten.

---

## 9. Phase 4 — Production Operations & Security ⏳ Planned

**Objective:** deployment inputs that cannot drift, secrets that rotate, and a scheduler that complains when it misses.

### 9.1 Supply-chain integrity (G9)

1. Run the existing `lock-refresh` GitHub workflow (workflow_dispatch, Ubuntu) to regenerate `requirements.lock` with Linux-correct hashes.
2. Switch the Dockerfile install to `pip install --require-hashes -r requirements.lock`.
3. Add a CI assertion that every entry in `requirements.lock` carries a hash — fails the build otherwise.
4. Keep the documented reason in `docs/` for why hashes are never regenerated on Windows.

### 9.2 Secrets management (G10)

- Migrate `ENCRYPTION_PASSWORD` → `SECRET_ENCRYPTION_PASSWORD` env var (user-side step, documented in `docs/runbook.md` with an exact migration checklist).
- Add a runbook section: rotation procedure (generate new key → re-encrypt `.env` via `scripts/encrypt_keys.py` → verify decryption → retire old key), including a verification command that fails loudly if any `ENCRYPTED_*` value no longer decrypts.
- Keep the startup contract intact: missing Telegram credentials still ends the run with exit code 2 after cleanup — a test already guards this; extend it to the new secret name.

### 9.3 Scheduler reliability (G11)

- `is_due()` already catches up missed runs; add repeated-miss alerting: after a configurable consecutive-miss count (from `ConfigManager`), emit an admin Telegram alert with the schedule name and last-success timestamp. **[B]** — notification behavior change; tests assert alert suppression below the threshold and emission at it.

### 9.4 Graceful shutdown ordering

`MainApp` cancellation exists; make the order contractual and tested: Telegram polling stops → background tasks cancelled → scheduler store closed → trading service cleaned → market provider closed → resources cleaned. One shutdown test asserts the observed order via instrumented doubles — this becomes the regression net for every future lifecycle change.

### 9.5 Opt-in tracing spans (deferred from Phase 2)

OpenTelemetry spans across the signal lifecycle, activated by a config flag defaulting to off; zero-cost when disabled. **[P]** — infrastructure change, proposal first.

**Phase 4 exit gate:** hash-assertion CI green post `lock-refresh` · secrets rotation runbook merged · shutdown-order test green · repeated-miss alert test green · default suite + ruff/mypy/goldens green.

---

## 10. Phase 5 — Alpha & Portfolio Research ⏳ Planned

**Objective:** graduate from per-symbol signal quality to portfolio-level alpha — through proposals, never by quietly widening the frozen gates.

### 10.1 Asset reference store **[P — approved-pending]**

OpenSpec change `add-asset-reference-store` is validated (`--strict`) with `proposal.md`, `spec.md`, `tasks.md`. Implementation starts only after explicit approval, in the proposal's task order: seed `asset_identifiers.json` (CoinGecko IDs + Messari slugs for the 10-symbol universe) resolves LINK/chainlink, DOT/polkadot, ASTR/astar-class mismatches at the fetcher boundary.

### 10.2 Cross-asset risk & allocation **[P]**

| Item | Design direction | Guardrail |
|---|---|---|
| Correlation-aware sizing | Use `analysis/correlation.py` outputs to scale position size down when open positions are highly correlated; decision logic lands in `domain/sizing.py` (stdlib-only, dataclass inputs) | Frozen RR/threshold gates untouched; sizing output is the only change; golden re-record **not** allowed — sizing is downstream of baselines or explicitly proposed with them |
| Regime-conditional allocation | `MarketConditionAnalyzer` regime maps to weight templates held in tracked config; selection logic in `application/` | Templates are data, not thresholds; reviewed as a proposal |
| Kelly / vol-targeting | Replace fixed-fractional sizing with configurable policy: fractional-Kelly with a hard cap, volatility-targeted scaling; policy selection via `ConfigManager` | Default remains current behavior until explicitly enabled — no silent behavior change |

### 10.3 Research integrations **[P]**

- **Factor library evaluation:** vet 101/191/158-style cross-sectional factor libraries as *candidate features* through the existing holdout + walk-forward gauntlet before any integration with `SignalGenerator`; a factor that cannot beat the gauntlet on fixtures is not wired.
- **Event-driven signals:** `EventDrivenStrategy` (CSV schema) integrates with news/on-chain sources through the same pipeline order and gates — events add candidates, never bypass `MultiTimeframeAnalyzer` or quality gates.
- **Feature store for training reuse** (deferred from Phase 3.9): the Phase 3 prediction trace is the read-side prerequisite; a training-reusable store still requires its own proposal.
- Every integration re-records goldens only via a dedicated, reviewed re-record commit.

**Phase 5 exit gate:** ≥3 factors survive the holdout gauntlet with documented metrics · sizing policy proposal approved and default-off · pipeline order test still green · goldens unchanged except explicit re-record commits · full gate suite green.

---

## 11. Phase 6 — Institutional Readiness ⏳ Planned

**Objective:** auditability and horizontal scale, without ever weakening the single-process correctness that exists today.

### 11.1 Compliance & audit **[P]**

- **Audit trail:** tamper-evident receipts for consequential actions (signal emission, artifact promotion, threshold-policy changes), verifiable offline from the receipt alone; integrate with the signal lifecycle via correlation IDs from Phase 2.
- **Trade reconstruction:** order → fill → PnL chain reconstructible from the append-only `PaperLedger` + tracker records for any `signal_id`; a reconstruction test round-trips a known sequence. The Phase 3 feature trace closes the model-side half of this chain.
- **Data lineage:** provenance chain (source → transform → feature → signal) recorded per run, satisfying "which source produced this decision" queries.

### 11.2 Scale-out **[P]**

- **Work-queue extraction:** Redis-backed symbol/timeframe work queue enabling multi-instance workers, with the composition root unchanged in shape — `create_trading_stack()` remains the only wiring point behind an upgraded implementation.
- **Exchange abstraction:** `ExchangeAdapter` protocol over the Binance fetcher first (no behavior change), then Bybit/OKX/Deribit adapters each behind their own proposal. Paper-only execution remains the default throughout.

---

## 12. Verification & Release Gates (cross-phase, non-negotiable)

Per change, smallest-first:

```bash
python -m pytest -m "not slow and not ml" -q
ruff check . && ruff format --check .
mypy domain
```

Per behavior change, add:

```bash
python -m pytest -m slow -q
sha256sum tests/golden/*.json
python -m pytest -m "not slow and not ml" -q --cov=domain --cov-fail-under=90
```

Phase 3 additionally requires:

```bash
python scripts/train_models.py --dry-run --data tests/fixtures/ohlcv_1h.csv
python scripts/run_walk_forward.py --data tests/fixtures/walk_forward_1h.csv
```

CI additionally runs: dependency audit, secrets guard, Docker build + healthcheck, plus the `model-quality` workflow (drift-check and walk-forward jobs). A phase is *done* when its exit-gate block in this document passes and `git status` shows only intended files staged.

---

## 13. Risk Register

| ID | Risk | L | I | Mitigation | Owner phase | State |
|---|---|---|---|---|---|---|
| R1 | Golden baselines silently coupled to tracked `config.json` | M | H | Phase 0 Option A: default in `ConfigManager` + golden-independence test | 0 | ✅ Closed |
| R2 | Memoization alters fetch timing → stale fundamentals within a run | M | M | Run-scoped memo only (cleared at cycle end); proposal includes staleness analysis | 1 | ✅ Closed |
| R3 | `PaperLedger` migration breaks append-only contract | L | H | Contract-preserving spec §6.1; concurrency + replay tests gate the merge | 1 | ✅ Closed |
| R4 | Calibration TTL deletes evidence needed for audit | L | M | Rotation keeps bounded history files; deletion window ≥ regulatory need | 2 | ✅ Closed |
| R5 | Adaptive thresholds drift into de-facto gate changes | M | H | Adaptive layer adjusts ranking only; frozen-gate immutability test | 2 | ✅ Closed |
| R6 | Drift detector false-positives trigger needless retraining | M | L | Configured alpha + min-window + Bonferroni correction + dependency-aware sampling; measured false-positive rate 2% over 100 stationary trials; `--dry-run` mode in CI; promotion stays behind the guard | 3 | ✅ Closed |
| R7 | Hash-pinned lock blocks a hotfix dependency bump | M | M | `lock-refresh` workflow is the sanctioned fast path; documented | 4 | ⏳ Open |
| R8 | Sizing/alpha changes silently re-record goldens | M | H | Re-records only via dedicated reviewed commits; pre-commit hash check | 5 | ⏳ Open |
| R9 | Multi-instance extraction breaks single-process correctness | L | H | Proposal-gated; composition root contract test preserved | 6 | ⏳ Open |
| R10 | Warm start refits the scaler → continued model sees a different feature space | M | H | Warm start reuses the persisted JSON scaler; scaler refit is forbidden on that path | 3 | ✅ Closed |
| R11 | A rejected candidate is promoted by an operator by accident | L | H | Rejected versions never touch the pointer; promotion is a separate explicit write; `--no-rollback-guard` logs loudly | 3 | ✅ Closed |
| R12 | Feature-trace writes add latency or disk pressure on the live path | L | M | Recorder is optional and disabled by default; failures degrade to warnings; files are runtime-only and gitignored | 3 | ✅ Closed |
| R13 | Golden baselines drift with the TensorFlow build, not with the code | M | M | Verified to fail on a clean checkout too; committed baseline left untouched; evidence and remediation path recorded in `docs/open_issues.md`; CI re-records in the Linux image | 3 | 🟡 Open — environmental |
| R14 | Training writes into the promoted artifact and breaks its integrity hashes | M | H | Fixed in Phase 3: training writes to a staging path, the registry copies into the new version, and a non-promoted candidate is evicted from the cache; enforced by `tests/unit/modeling/test_training_isolation.py` | 3 | ✅ Closed |

---

## 14. Resource Plan

| Phase | Calendar | Eng. days | Depends on | Parallelizable with |
|---|---|---|---|---|
| 0 — Hygiene | 1 week | 3 | — | — |
| 1 — Architecture & I/O | 2 weeks | 6 | 0 | 2 (partially) |
| 2 — Signal & Observability | 2 weeks | 6 | 0 | 1 |
| 3 — Model Lifecycle | 3 weeks | 9 | 1 | 4 (partially) |
| 4 — Ops & Security | 2 weeks | 6 | 1 | 3 (partially) |
| 5 — Alpha Research | 4 weeks | 12 | 3 | 6 scoping |
| 6 — Institutional | ongoing | — | 4–5 | — |

**Critical path:** 0 → 1 → 3 → 5. Phases 0–3 consumed ≈ 8 weeks; the remaining path to institutional-grade readiness is ≈ 6 more weeks.

---

## 15. Definition of Done — per-phase summary

| Phase | Done means… |
|---|---|
| 0 | ✅ Config contradiction resolved *and tested*; dependency set truthful; guards green |
| 1 | ✅ Zero blocking sqlite on stack-reachable paths; one fetch per datum per run, proven by test |
| 2 | ✅ Calibration survives restart, is TTL-bounded, rotates; replay is idempotent; every lifecycle transition emits metrics + correlation IDs |
| 3 | ✅ Retraining detects drift, warm-starts, and refuses to promote degraded models — all on fixtures in CI; every emitted signal carries a reconstructible feature trace |
| 4 | Lock is hash-pinned on Linux; secrets rotate by runbook; shutdown order is contractual; missed runs alert |
| 5 | ≥3 gauntlet-proven factors; sizing policy default-off and proposal-approved; pipeline order inviolate |
| 6 | Every signal reconstructible end-to-end; adapter protocol exists with Binance-only behavior parity |

---

## Appendix A — File map of record

```
config/settings.py            ConfigManager, TTL defaults, signal_threshold ✅, drift/promotion knobs (Phase 3)
config/logger.py              loguru setup + correlation binding ✅ (Phase 2)
data/warehouse.py             IndicatorHistoryWarehouse (aiosqlite) ✅
data/sources/                 fetchers; run-scoped memo boundary ✅ (Phase 1)
trading/ledger.py             PaperLedger (aiosqlite) ✅ (Phase 1)
strategy/signal_generator.py  pipeline head; optional prediction-trace recorder (Phase 3)
strategy/prediction_trace.py  prediction-time feature trace writer (Phase 3)
strategy/signal_tracker.py    calibration persistence + TTL + rotation ✅ (Phase 2)
strategy/multi_timeframe.py   deduped OHLCV path ✅
domain/sizing.py              correlation-aware sizing (Phase 5, stdlib-only)
application/gate_config.py    single gate constructor — untouched by all phases
services/trading_service.py   composition root; memo scope; reconciliation; metrics wiring; trace wiring
modeling/drift.py             KS drift detection + versioned drift summary ✅ (Phase 3)
modeling/promotion.py         promotion/rollback policy — pure decision function ✅ (Phase 3)
modeling/artifacts.py         ArtifactRegistry + version listing/promotion ✅ (Phase 3)
modeling/model_manager.py     train_model(promote=, warm_start=) → TrainingOutcome ✅ (Phase 3)
modeling/models.py            fit(warm_start=) for LSTM/XGBoost ✅ (Phase 3)
scripts/train_models.py       CLI: --dry-run / --warm-start / --data + drift & promotion report ✅ (Phase 3)
scripts/run_holdout.py        + versioned monte_carlo block ✅ (Phase 3)
scripts/run_walk_forward.py   fold hygiene + metrics + leakage flags ✅ (Phase 3)
backtesting/montecarlo.py     versioned bootstrap CI block ✅ (Phase 3)
backtesting/historical_signals.py  shared candle/signal/metric helpers ✅ (Phase 3)
strategy/prediction_trace.py  prediction-time feature trace writer ✅ (Phase 3)
utils/scheduler_store.py      repeated-miss alerting (Phase 4)
utils/security.py             SECRET_ENCRYPTION_PASSWORD + rotation (Phase 4)
tests/unit/modeling/test_drift.py          drift detection contract ✅
tests/unit/modeling/test_promotion.py      promotion/rollback contract ✅
tests/unit/modeling/test_training_isolation.py   training never mutates a promoted artifact ✅
tests/unit/scripts/test_train_models_lifecycle.py   trainer-level lifecycle ✅
tests/unit/backtesting/test_montecarlo.py   versioned bootstrap contract ✅
tests/unit/backtesting/test_walk_forward_runner.py    walk-forward job contract ✅
tests/unit/strategy/test_prediction_trace.py         feature trace contract ✅
tests/fixtures/drift_stable_1h.csv    stationary drift fixture (no drift expected) ✅
tests/fixtures/drift_shifted_1h.csv   shifted drift fixture (drift expected) ✅
tests/fixtures/walk_forward_1h.csv   walk-forward validation fixture ✅
tests/unit/scripts/test_dead_code_guard.py   extended to backtrader ✅ (Phase 0)
tests/unit/test_architecture.py              event-loop hygiene + import direction ✅ (Phases 1, 5, 6)
docs/runbook.md               secrets rotation, lock-refresh, training procedures
docs/adr/                     one ADR per phase-level decision (config.json, memoization, audit, model lifecycle ✅)
openspec/changes/             one validated change per [P] item before implementation
.github/workflows/model-quality.yml    drift-check + walk-forward + lifecycle jobs ✅ (Phase 3)
```

## Appendix B — Sources of truth referenced by this plan

- `CLAUDE.md` — architecture contracts, commands, coding conventions, repository map
- `docs/open_issues.md` — verified open/closed register
- `docs/exceptions_audit.md` — 159 audited exception sites
- `docs/runbook.md` — operational procedures
- `openspec/changes/add-asset-reference-store/` — validated proposal awaiting approval
- `tests/golden/` — baseline hashes governing every gate in §12

---

**Prepared**: 2026-10-19 · **Version**: 3.0 · **Status**: Active plan of record — supersedes v2.0
