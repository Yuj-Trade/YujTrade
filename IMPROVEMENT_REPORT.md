# YujTrade Engineering Improvement Plan

**From Production-Ready v0.4.0 to Institutional Grade — a verified, phased implementation roadmap**

| Document Control | |
|---|---|
| Version | 2.0 (supersedes the v1.0 checklist report) |
| Date | 2026-10-18 |
| Baseline | Tag `v0.4.0-production-ready` |
| Scope | All runtime packages, `scripts/`, `tests/`, CI, and documentation |
| Verification standard | Every claim in this document is backed by a reproducible command in §11 |
| Change discipline | `openspec/AGENTS.md` governs all capability work; CLAUDE.md rules apply throughout |

---

## 1. Executive Summary

YujTrade is an asynchronous, spec-driven crypto trading-signal system with a strictly layered architecture (`domain` ← `application` ← infrastructure), a single composition root (`services/trading_service.py:create_trading_stack()`), deterministic golden baselines, and verified model artifacts with SHA-256 integrity.

**Verified baseline at v0.4.0:**

| Dimension | State | Evidence |
|---|---|---|
| Tests | ~330 collected, default suite green; 100% `domain` coverage gate | `python -m pytest -m "not slow and not ml" -q` |
| Lint & types | Zero ruff findings; `ruff format --check` clean; `mypy domain` clean | §11 gate block |
| Golden determinism | 59 signals / 15 trades, byte-stable; hermetic recorder resets warehouse state | `python -m pytest -m slow -q`; `signals_baseline.json` / `backtest_baseline.json` |
| Security posture | Zero pickle, zero secrets in git, zero bare `except:`, 159 audited exception sites | `docs/exceptions_audit.md`, CI `secrets-guard` job |
| Container | Podman image builds, digest-pinned base, non-root `appuser`, in-container healthcheck exit 0 | `Dockerfile`, `scripts/docker_healthcheck.py` |
| Model integrity | `ArtifactRegistry` enforces metadata + SHA-256 on load; mismatch → `model_unavailable` | `modeling/artifacts.py`, ADR series |

**The gap to close.** The system is *correct* but not yet *self-improving*: SQLite I/O is not uniformly async, signal calibration state is unbounded and unpersisted, model retraining lacks drift detection and automated rollback, observability is fragmented, the dependency lock is hash-less (blocked on platform), and alpha research (multi-asset risk, regime templates, event-driven signals) is designed but unwired.

**Plan of record.** Six phases over ~14 calendar weeks (parallelizable after Phase 3), each with explicit work items, file-level ownership, acceptance criteria, exit gates, and a risk register. Items marked **[P]** require an approved OpenSpec proposal before implementation, per repository policy. Items marked **[B]** change runtime behavior and require the `[behavior-change]` commit tag plus accompanying tests. Frozen contracts (`LONG_TERM_CONFIG` thresholds, paper-only execution, exit-code-2 startup, gate centralization via `application/gate_config.py`) are never modified by this plan.

---

## 2. Current State Assessment

### 2.1 Strengths to preserve

1. **Layered purity.** `domain/` is stdlib-only, enforced by `tests/unit/test_architecture.py`. All new logic in this plan respects the import direction `domain` ← `application` ← infrastructure.
2. **Single composition root.** `create_trading_stack()` is the only wiring point; caller-owned cleanup (`provider.close()`, `service.cleanup()`, `resources.cleanup()`).
3. **Signal pipeline order is contractual:** `SignalGenerator` → `MultiTimeframeAnalyzer` (score ≥ 0.3, no direction conflict) → per-timeframe quality gates → `SignalRanking` (per-TF cap, then global cap). Gate construction flows only through `application/gate_config.py:build_gate_config()`.
4. **Artifact policy.** Mandatory verified metadata (`data_start`, `data_end`, `feature_list`, `params`, `git_commit`, `library_versions`, `files_sha256`); JSON scalers only; prediction never trains.
5. **Determinism.** Golden JSON baselines with SHA-256 pre-commit checks; holdout paths causal and isolated from live external/ML data.

### 2.2 Verified gaps (evidence-confirmed, not assumed)

| # | Gap | Evidence | Phase |
|---|---|---|---|
| G1 | `config.json` is tracked while `.gitignore:194` lists it, and golden baselines silently depend on its `signal_threshold: 10` | `git ls-files config.json`; `git check-ignore` | 0 |
| G2 | `backtrader` declared in `requirements.txt`, absent from prod imports and from `requirements.lock` | requirements scan | 0 |
| G3 | `PaperLedger` performs blocking `sqlite3` I/O on async paths | `trading/ledger.py` | 1 |
| G4 | `get_fundamental_data` / `get_onchain_data` hit the network once per symbol×timeframe (~5×/run) when Redis is absent | `data/sources/` call-graph | 1 |
| G5 | `signal_history.json` calibration store has no TTL, rotation, or size bound | `strategy/signal_tracker.py` | 2 |
| G6 | `AdaptiveThresholdManager` state is in-memory only — calibration lost on restart | `strategy/` | 2 |
| G7 | No correlation IDs, partial metrics wiring, no tracing spans across the signal lifecycle | `common/metrics.py` audit | 2 |
| G8 | Retraining has no drift detection, no warm-start, no automated OOS-degradation rollback | `scripts/train_models.py` | 3 |
| G9 | `requirements.lock` is hash-less; Windows-built hashes would be wrong-platform | `docs/open_issues.md` | 4 |
| G10 | `ENCRYPTION_PASSWORD` not yet migrated to `SECRET_ENCRYPTION_PASSWORD`; no documented rotation procedure | `utils/security.py`, runbook | 4 |
| G11 | Missed scheduler runs are caught up silently — no repeated-miss alerting | `utils/scheduler_store.py` | 4 |
| G12 | Position sizing is per-symbol only; no cross-asset correlation risk; allocation is fixed-fractional | `trading/risk_manager.py`, `domain/sizing.py` | 5 |
| G13 | `ExchangeAdapter` abstraction absent (Binance-only data path); single-process scaling ceiling | `data/sources/binance_fetcher.py` | 6 |

---

## 3. Guiding Principles (binding for every phase)

1. **Proposals before capabilities.** Any new capability, breaking change, or architecture work follows `openspec/AGENTS.md`: scaffold under `openspec/changes/<verb-led-kebab-id>/`, `openspec validate <id> --strict`, implement only after approval.
2. **Frozen contracts.** `LONG_TERM_CONFIG` thresholds and indicator formulas are frozen (shape data only). Paper execution is the default; nothing in this plan lowers quality gates or enables live execution.
3. **No hardcoded policy.** Thresholds, TTLs, data limits, and model bounds come from `ConfigManager` / existing helpers — never literals.
4. **Zero comments, loguru logging, async everywhere, Python 3.13 syntax.** Rationale lives in `docs/` and ADRs, not in code.
5. **One concern per commit.** Prefixes `chore:`/`fix:`/`test:`/`style:`/`docs:`/`build:`/`ci:`; `[behavior-change]` tag when runtime behavior changes; golden SHA-256 unchanged unless the commit *is* a golden re-record with real data.
6. **Tests are the only proof.** Logs never substitute for tests; the smallest relevant test runs first, then the full default gate.

---

## 4. Phase 0 — Hygiene & Configuration Truth (Week 1)

**Objective:** eliminate every contradiction between what the repository *says* and what it *is*. Zero risk, high trust impact.

### 4.1 Resolve the `config.json` contradiction — **Priority 1** [P]

**Problem.** Tracked in git, listed in `.gitignore:194`, and the golden baselines depend on `signal_threshold: 10` living in it. Any checkout without this file, or any edit to it, silently shifts golden output.

**Recommended decision — Option A (untrack):**
1. Record `signal_threshold: 10` as the explicit default in `ConfigManager.DEFAULT_CONFIG` (`config/settings.py`).
2. Add a golden-independence test asserting baseline output is identical with and without a `config.json` override present.
3. `git rm --cached config.json`; keep the `.gitignore` entry; document in `README.md` that the file is generated at runtime.
4. Re-verify golden hashes unchanged; if the default re-record is needed, it is a single dedicated `[behavior-change]` commit.

**Option B (document as tracked tuning):** remove the `.gitignore` line, add a tracked `config.example.json`, and add a CI assertion that `signal_threshold` equals the golden-pinned value. Option B keeps drift visible but couples goldens to a mutable file — accepted only if Option A is rejected.

**Exit criterion:** exactly one of the two states holds, asserted by a test, and CLAUDE.md's "untracked runtime override" sentence matches reality.

### 4.2 Dependency hygiene

| ID | Task | Detail | Status |
|---|---|---|---|
| 0.2.1 | Pin `aiosqlite` | `aiosqlite==0.22.1` now present in `requirements.lock` | ✅ Done — verify only |
| 0.2.2 | Remove `backtrader` | Not imported by any prod package; absent from the lock. Delete from `requirements.txt`; guard with an importer-absence test mirroring `test_dead_code_guard.py` | ⏳ |
| 0.2.3 | Hash-pinned lock prep | Blocked on G9; tracked under Phase 4.4 with the `lock-refresh` workflow path | Phase 4 |

### 4.3 Dead-code verification (completed, keep guarded)

- [x] `scripts/run_golden.py` removed (duplicate of `tests/golden/record_signals.py`, hardcoded `C:/ME/YujTrade` path)
- [x] `scripts/install_mock.py` removed (pandas_ta mock, zero importers)
- [x] `symtemp.txt` removed (stale 208-byte symbol list)
- [x] Four caller-less fetcher methods removed (`get_exchange_info`, `get_all_futures_symbols`, `get_circulating_supply`, `get_all_assets`)
- Guard: `tests/unit/scripts/test_dead_code_guard.py` enforces zero references repo-wide. Extend it with the `backtrader` importer-absence check in 0.2.2.

### 4.4 Stale documentation & naive datetime (completed)

- [x] `BacktestingEngine` references purged from `test_signal_tracker.py` / `test_signal_generator.py` prose (engine deleted in v4.0)
- [x] README test count corrected (321, was "197")
- [x] `app/telegram_bot.py` display string now timezone-aware UTC

**Phase 0 exit gate:** default pytest green · ruff/mypy clean · golden SHA-256 unchanged · a passing test asserts the resolved `config.json` state · no undeclared dependency in `requirements.txt`.

---

## 5. Phase 1 — Architecture & I/O Discipline (Weeks 2–3)

**Objective:** zero blocking I/O on the event loop, one network fetch per unique datum per run, and a dependency set that tells the truth.

### 5.1 Complete the async-SQLite migration

| Store | State | Action |
|---|---|---|
| `IndicatorHistoryWarehouse` | ✅ `aiosqlite`; measured 174 ms → 23 ms per cycle | None — regression-test the bound |
| `SchedulerStore` | ✅ `aiosqlite` | None |
| `PaperLedger` | ⏳ blocking `sqlite3` | Migrate per spec below |

**PaperLedger migration spec [B]:**
- Preserve the append-only contract and unique `signal_id` constraint verbatim; the migration changes transport, not semantics.
- Implementation: replace the synchronous connection with `aiosqlite`; every write path (`record_fill`, `resolve_outcome`) becomes `async def`; callers in `services/trading_service.py` and `app/tasks.py` updated at the composition root only.
- Add a concurrency test: two coroutines appending distinct `signal_id` values under `asyncio.gather` produce two rows, in deterministic file order.
- Add an event-loop hygiene test: no `sqlite3` import remains on any import path reachable from `create_trading_stack()` (extend `tests/unit/test_architecture.py` or add a targeted guard).

### 5.2 Run-level fetch memoization [P] [B]

**Problem (G4).** Without Redis, `get_fundamental_data` / `get_onchain_data` are fetched once per symbol per timeframe — 5 identical network calls per symbol per run.

**Design.**
- Introduce a per-analysis-cycle memo keyed by `(run_id, symbol, source, params_hash)` inside `TradingService`, cleared at cycle end. This is *not* the Redis cache — it is run-scoped deduplication with a lifetime bound by the run.
- TTL semantics unchanged (`get_cache_ttl()` remains the only TTL source); the memo only collapses duplicates within a cycle.
- Because this changes fetch timing (open_issues #6), it ships as an approved OpenSpec proposal (`add-run-level-fetch-memoization` or equivalent) with before/after network-call counts in the proposal's evidence section.
- Acceptance: a unit test with a counting fake fetcher asserts exactly one upstream call per `(symbol, source)` per run across all five timeframes.

**Already completed (keep guarded):** `mtf_analysis` double-caching removed; `CacheKeyBuilder.mtf_analysis_key` removed; TTL-key deletion asserted by `tests/unit/common/test_cache_ttl_config.py` (23 assertions) and the AST literal guard `tests/unit/test_cache_ttl_source.py`.

### 5.3 Remaining audit

- [ ] Sweep `data/sources/` for further definition-only methods using the dead-code-guard pattern (proof of zero callers before deletion).
- [ ] Confirm no path re-introduces integer-literal `ex=`/`cache_ttl` (guard already exists — no action unless red).

**Phase 1 exit gate:** event-loop hygiene test green (no blocking sqlite on stack-reachable paths) · counting-fetcher test proves ≤1 upstream call per datum per run · `requirements.txt` contains only imported dependencies · default suite + ruff/mypy green · golden hashes unchanged.

---

## 6. Phase 2 — Signal Quality, Calibration & Observability (Weeks 4–5)

**Objective:** make the signal lifecycle measurable, bounded, and idempotent — the difference between "signals that work" and "signals you can prove work."

### 6.1 Persist and bound adaptive thresholds (G5, G6)

- **Persistence:** `AdaptiveThresholdManager` state serialized to `signal_history.json` on shutdown and loaded on startup; schema versioned; corrupt file → warning + fresh state (never a crash, mirroring the artifact policy).
- **TTL & rotation:** calibration records older than a configurable TTL (default 30 days, via `ConfigManager`, never a literal) are pruned at write time; a size cap (record count bound) triggers rotation to `signal_history.<n>.json` with the same gitignore treatment as the primary file.
- **Frozen-threshold guard:** adaptive values adjust *ranking confidence only* — the frozen `LONG_TERM_CONFIG` per-timeframe `min_confidence_threshold` values remain the acceptance gates. An immutable test asserts `LONG_TERM_CONFIG` is byte-identical to a pinned fixture.

### 6.2 Lifecycle correctness

- **Expiry reconciliation (done):** `TradingService.reconcile_pending_signals()` resolves expired signals through `domain/outcome.py` — shared by live, paper, and backtest resolution paths. Keep a test asserting all three paths produce identical outcome records.
- **Idempotency key:** `signal_id` (symbol + tf + timestamp + type) already deduplicates; add a run-scoped idempotency wrapper so a retried analysis cycle cannot double-record in `SignalTracker` or the `PaperLedger`. Acceptance: replaying the same cycle twice yields one tracker record and one ledger row.
- **Rejection semantics (contract, no change):** healthy rejection is `None` and stays distinct from analysis failure — a test asserts invalid/unavailable inputs retain their exception semantics rather than collapsing into no-signal.

### 6.3 Observability spine (G7)

1. **Correlation IDs.** Bind a `run_id`/`signal_id` context via loguru `logger.bind()` at cycle start; every log line in generation → gating → ranking → resolution carries both. A test greps captured logs for the bound pair across one simulated cycle.
2. **Metrics wiring.** Counters in `common/metrics.py` cover: candidates generated, per-gate rejections (gate name as label), signals emitted, expiry resolutions, artifact hash mismatches. Wire every path in `TradingService` + `SignalTracker`; a unit test asserts counters advance for each lifecycle transition.
3. **Tracing (opt-in).** OpenTelemetry spans for the pipeline stages, activated by a config flag defaulting to off; zero-cost when disabled. **[P]** — infrastructure change, proposal first.

**Phase 2 exit gate:** restart-persistence test for adaptive state · rotation/TTL test · idempotent-replay test · correlation-ID and metrics-advance tests · default suite + ruff/mypy green · goldens unchanged (Phase 2 must not alter signal output; any output change fails the phase).

---

## 7. Phase 3 — Model Lifecycle & Data Robustness (Weeks 6–8)

**Objective:** a closed retraining loop that detects drift, retrains incrementally, and rolls itself back when quality regresses — with no human guesswork.

### 7.1 Automated retraining pipeline (`scripts/train_models.py`) [B]

| Capability | Specification | Acceptance |
|---|---|---|
| Drift detection | Two-sample KS test per feature, training window vs. live window; thresholds from `ConfigManager` (`drift_alpha`, min window size) — never literals | Synthetic fixture with shifted distribution flags drift; unchanged distribution does not |
| Warm-start | Optional `--warm-start` loads current artifact weights as initialization; new artifact version still carries full metadata + fresh OOS metrics | Warm-start run trains measurably faster and passes the same OOS floor |
| Automated rollback | Post-train, if OOS directional accuracy or RMSE degrades beyond a configured bound vs. the current version, the new version is *not* promoted — pointer stays; the attempt is logged with its metrics | Fixture with poisoned data never promotes; healthy retrain promotes |
| Scheduling | Nightly/weekly CI workflow invoking training with `--dry-run` drift check (network training remains user-side per runbook) | Workflow YAML lints; drift-check job green on unchanged data |

### 7.2 Feature reproducibility (G8 adjacent)

- Persist the exact feature vector schema + values used at prediction time alongside signal records (JSON, gitignored runtime data), keyed by `signal_id`, enabling later reconciliation of "what the model saw."
- Evaluate a persisted feature store for training reuse — **[P]**; until proposed, `FeatureEngineer` remains deterministic-per-run and unchanged.

### 7.3 Backtest & holdout hardening (already strong, finish the wiring)

- **Done & guarded:** `HoldoutGuard` (15% protected slice + explicit `--confirm`); `scripts/run_holdout.py` full metrics (trades, win rate, Sharpe, bootstrap CI); 1-row purge between train/OOS; artifact integrity → `model_unavailable`.
- **Wire `WalkForwardValidator` into CI** as a scheduled job on deterministic fixtures; assert fold metrics within tolerance and zero leakage flags.
- **Monte Carlo into the holdout report:** `backtesting/montecarlo.py` bootstrap CI appended to the holdout report JSON with a stable schema (versioned key), so regressions in distributional robustness are diffable run-over-run.
- **Causality guard (contract, no change):** holdout and historical paths (`backtesting/historical_signals.py`) stay causal and isolated from live external/ML data; extend the existing isolation test to cover any new store added by this phase.

**Phase 3 exit gate:** drift fixture + rollback fixture tests green · walk-forward CI job green on fixtures · holdout report contains versioned bootstrap CI · artifact policy tests unchanged · goldens unchanged · default suite + ruff/mypy green.

---

## 8. Phase 4 — Production Operations & Security (Weeks 9–10)

**Objective:** deployment inputs that cannot drift, secrets that rotate, and a scheduler that complains when it misses.

### 8.1 Supply-chain integrity (G9)

1. Run the existing `lock-refresh` GitHub workflow (workflow_dispatch, Ubuntu) to regenerate `requirements.lock` with Linux-correct hashes.
2. Switch the Dockerfile install to `pip install --require-hashes -r requirements.lock`.
3. Add a CI assertion that every entry in `requirements.lock` carries a hash — fails the build otherwise.
4. Keep the documented reason in `docs/` for why hashes are never regenerated on Windows.

### 8.2 Secrets management (G10)

- Migrate `ENCRYPTION_PASSWORD` → `SECRET_ENCRYPTION_PASSWORD` env var (user-side step, documented in `docs/runbook.md` with an exact migration checklist).
- Add a runbook section: rotation procedure (generate new key → re-encrypt `.env` via `scripts/encrypt_keys.py` → verify decryption → retire old key), including a verification command that fails loudly if any `ENCRYPTED_*` value no longer decrypts.
- Keep the startup contract intact: missing Telegram credentials still ends the run with exit code 2 after cleanup — a test already guards this; extend it to the new secret name.

### 8.3 Scheduler reliability (G11)

- `is_due()` already catches up missed runs; add repeated-miss alerting: after a configurable consecutive-miss count (from `ConfigManager`), emit an admin Telegram alert with the schedule name and last-success timestamp. **[B]** — notification behavior change; tests assert alert suppression below the threshold and emission at it.

### 8.4 Graceful shutdown ordering

`MainApp` cancellation exists; make the order contractual and tested: Telegram polling stops → background tasks cancelled → scheduler store closed → trading service cleaned → market provider closed → resources cleaned. One shutdown test asserts the observed order via instrumented doubles — this becomes the regression net for every future lifecycle change.

**Phase 4 exit gate:** hash-assertion CI green post `lock-refresh` · secrets rotation runbook merged · shutdown-order test green · repeated-miss alert test green · default suite + ruff/mypy/goldens green.

---

## 9. Phase 5 — Alpha & Portfolio Research (Weeks 11–14)

**Objective:** graduate from per-symbol signal quality to portfolio-level alpha — through proposals, never by quietly widening the frozen gates.

### 9.1 Asset reference store **[P — approved-pending]**

OpenSpec change `add-asset-reference-store` is validated (`--strict`) with `proposal.md`, `spec.md`, `tasks.md`. Implementation starts only after explicit approval, in the proposal's task order: seed `asset_identifiers.json` (CoinGecko IDs + Messari slugs for the 10-symbol universe) resolves LINK/chainlink, DOT/polkadot, ASTR/astar-class mismatches at the fetcher boundary.

### 9.2 Cross-asset risk & allocation **[P]**

| Item | Design direction | Guardrail |
|---|---|---|
| Correlation-aware sizing | Use `analysis/correlation.py` outputs to scale position size down when open positions are highly correlated; decision logic lands in `domain/sizing.py` (stdlib-only, dataclass inputs) | Frozen RR/threshold gates untouched; sizing output is the only change; golden re-record **not** allowed — sizing is downstream of baselines or explicitly proposed with them |
| Regime-conditional allocation | `MarketConditionAnalyzer` regime maps to weight templates held in tracked config; selection logic in `application/` | Templates are data, not thresholds; reviewed as a proposal |
| Kelly / vol-targeting | Replace fixed-fractional sizing with configurable policy: fractional-Kelly with a hard cap, volatility-targeted scaling; policy selection via `ConfigManager` | Default remains current behavior until explicitly enabled — no silent behavior change |

### 9.3 Research integrations **[P]**

- **Factor library evaluation:** vet 101/191/158-style cross-sectional factor libraries as *candidate features* through the existing holdout + walk-forward gauntlet before any integration with `SignalGenerator`; a factor that cannot beat the gauntlet on fixtures is not wired.
- **Event-driven signals:** `EventDrivenStrategy` (CSV schema) integrates with news/on-chain sources through the same pipeline order and gates — events add candidates, never bypass `MultiTimeframeAnalyzer` or quality gates.
- Every integration re-records goldens only via a dedicated, reviewed re-record commit.

**Phase 5 exit gate:** ≥3 factors survive the holdout gauntlet with documented metrics · sizing policy proposal approved and default-off · pipeline order test still green · goldens unchanged except explicit re-record commits · full gate suite green.

---

## 10. Phase 6 — Institutional Readiness (Ongoing)

**Objective:** auditability and horizontal scale, without ever weakening the single-process correctness that exists today.

### 10.1 Compliance & audit **[P]**

- **Audit trail:** tamper-evident receipts for consequential actions (signal emission, artifact promotion, threshold-policy changes), verifiable offline from the receipt alone; integrate with the signal lifecycle via correlation IDs from §6.3.
- **Trade reconstruction:** order → fill → PnL chain reconstructible from the append-only `PaperLedger` + tracker records for any `signal_id`; a reconstruction test round-trips a known sequence.
- **Data lineage:** provenance chain (source → transform → feature → signal) recorded per run, satisfying "which source produced this decision" queries.

### 10.2 Scale-out **[P]**

- **Work-queue extraction:** Redis-backed symbol/timeframe work queue enabling multi-instance workers, with the composition root unchanged in shape — `create_trading_stack()` remains the only wiring point behind an upgraded implementation.
- **Exchange abstraction:** `ExchangeAdapter` protocol over the Binance fetcher first (no behavior change), then Bybit/OKX/Deribit adapters each behind their own proposal. Paper-only execution remains the default throughout.

---

## 11. Verification & Release Gates (cross-phase, non-negotiable)

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

CI additionally runs: dependency audit, secrets guard, Docker build + healthcheck. A phase is *done* when its exit-gate block in this document passes and `git status` shows only intended files staged.

---

## 12. Risk Register

| ID | Risk | L | I | Mitigation | Owner phase |
|---|---|---|---|---|---|
| R1 | Golden baselines silently coupled to tracked `config.json` | M | H | Phase 0 Option A: default in `ConfigManager` + golden-independence test | 0 |
| R2 | Memoization alters fetch timing → stale fundamentals within a run | M | M | Run-scoped memo only (cleared at cycle end); proposal includes staleness analysis | 1 |
| R3 | `PaperLedger` migration breaks append-only contract | L | H | Contract-preserving spec §5.1; concurrency + replay tests gate the merge | 1 |
| R4 | Calibration TTL deletes evidence needed for audit | L | M | Rotation keeps bounded history files; deletion window ≥ regulatory need | 2 |
| R5 | Adaptive thresholds drift into de-facto gate changes | M | H | Adaptive layer adjusts ranking only; frozen-gate immutability test | 2 |
| R6 | Drift detector false-positives trigger needless retraining | M | L | Configured alpha + min-window; dry-run mode in CI; human gate for promotion | 3 |
| R7 | Hash-pinned lock blocks a hotfix dependency bump | M | M | `lock-refresh` workflow is the sanctioned fast path; documented | 4 |
| R8 | Sizing/alpha changes silently re-record goldens | M | H | Re-records only via dedicated reviewed commits; pre-commit hash check | 5 |
| R9 | Multi-instance extraction breaks single-process correctness | L | H | Proposal-gated; composition root contract test preserved | 6 |

---

## 13. Resource Plan

| Phase | Calendar | Eng. days | Depends on | Parallelizable with |
|---|---|---|---|---|
| 0 — Hygiene | 1 week | 3 | — | — |
| 1 — Architecture & I/O | 2 weeks | 6 | 0 | 2 (partially) |
| 2 — Signal & Observability | 2 weeks | 6 | 0 | 1 |
| 3 — Model Lifecycle | 3 weeks | 9 | 1 | 4 (partially) |
| 4 — Ops & Security | 2 weeks | 6 | 1 | 3 (partially) |
| 5 — Alpha Research | 4 weeks | 12 | 3 | 6 scoping |
| 6 — Institutional | ongoing | — | 4–5 | — |

**Critical path:** 0 → 1 → 3 → 5. First five phases ≈ 14 weeks to institutional-grade readiness.

---

## 14. Definition of Done — per-phase summary

| Phase | Done means… |
|---|---|
| 0 | Config contradiction resolved *and tested*; dependency set truthful; guards green |
| 1 | Zero blocking sqlite on stack-reachable paths; one fetch per datum per run, proven by test |
| 2 | Calibration survives restart, is TTL-bounded, rotates; replay is idempotent; every lifecycle transition emits metrics + correlation IDs |
| 3 | Retraining detects drift, warm-starts, and refuses to promote degraded models — all on fixtures in CI |
| 4 | Lock is hash-pinned on Linux; secrets rotate by runbook; shutdown order is contractual; missed runs alert |
| 5 | ≥3 gauntlet-proven factors; sizing policy default-off and proposal-approved; pipeline order inviolate |
| 6 | Every signal reconstructible end-to-end; adapter protocol exists with Binance-only behavior parity |

---

## Appendix A — File map of record

```
config/settings.py            ConfigManager, TTL defaults, signal_threshold (Phase 0 Option A)
config/logger.py              loguru setup (correlation binding lands here, Phase 2)
data/warehouse.py             IndicatorHistoryWarehouse (aiosqlite) ✅
data/sources/                 fetchers; memoization boundary (Phase 1, proposal-gated)
trading/ledger.py             PaperLedger → aiosqlite migration (Phase 1)
strategy/signal_generator.py  pipeline head; factor integration point (Phase 5, gated)
strategy/signal_tracker.py    calibration persistence + TTL + rotation (Phase 2)
strategy/multi_timeframe.py   deduped OHLCV path ✅
domain/sizing.py              correlation-aware sizing (Phase 5, stdlib-only)
application/gate_config.py    single gate constructor — untouched by all phases
services/trading_service.py   composition root; memo scope; reconciliation; metrics wiring
scripts/train_models.py       drift + warm-start + rollback (Phase 3)
scripts/run_holdout.py        + bootstrap CI schema (Phase 3)
backtesting/montecarlo.py     wired to holdout report (Phase 3)
backtesting/walk_forward.py   scheduled CI fixture job (Phase 3)
utils/scheduler_store.py      repeated-miss alerting (Phase 4)
utils/security.py             SECRET_ENCRYPTION_PASSWORD + rotation (Phase 4)
tests/unit/scripts/test_dead_code_guard.py   extended to backtrader (Phase 0)
tests/unit/test_architecture.py              event-loop hygiene + import direction (Phases 1, 5, 6)
docs/runbook.md               secrets rotation, lock-refresh, training procedures
docs/adr/                     one ADR per phase-level decision (config.json, memoization, audit)
openspec/changes/             one validated change per [P] item before implementation
```

## Appendix B — Sources of truth referenced by this plan

- `CLAUDE.md` — architecture contracts, commands, coding conventions, repository map
- `docs/open_issues.md` — verified open/closed register (2026-10-14 state)
- `docs/exceptions_audit.md` — 159 audited exception sites
- `docs/runbook.md` — operational procedures
- `openspec/changes/add-asset-reference-store/` — validated proposal awaiting approval
- `tests/golden/` — baseline hashes governing every gate in §11

---

**Prepared**: 2026-10-18 · **Version**: 2.0 · **Status**: Active plan of record — supersedes v1.0
