# Open Issues Register

Status as of 2026-10-14 (v4.0 + cache/TTL phase complete, verified locally).
A `blocked` entry never guesses missing content; it records the reason and moves on.
Resolved items live under Resolved with their evidence; nothing resolved stays
in the open lists.

## Resolved — verified this session

- [x] Container image verified with Podman: `podman build --format docker`
  succeeds, `scripts/docker_healthcheck.py` exits 0 in-container, the image
  runs as `appuser` with writable `runs artifacts logs reports`.
- [x] TA-Lib on `python:3.13-slim-bookworm`: `TA-Lib==0.8.1` installs from the
  lockfile and imports inside the image.
- [x] Base-image digest pinned: `sha256:a1165e27...5f4d641`, resolved live
  from the registry, not guessed.
- [x] Full-repo lint is zero: `ruff check .` and `ruff format --check .` pass
  (the v3.0 baseline of 948 errors is gone; the last of it fell to the
  Python-3.13 modernization in phase 8). `mypy domain` is clean.
- [x] Golden is hermetic and non-trivial: the determinism test resets
  `runs/indicator_history.db*` before recording, so output no longer depends
  on local warehouse state. 59 signals / 15 trades, byte-stable across runs:
  `signals_baseline.json` `CAC5D8A6...`, `backtest_baseline.json` `833F5643...`.
- [x] `docs/exceptions_audit.md` regenerated: all 159 `except Exception`
  sites re-verified with current line numbers; every handler logs or
  re-raises.
- [x] Cache TTL consistency (3 commits, no behavior change): every effective
  TTL asserted by `tests/unit/common/test_cache_ttl_config.py` (23 tests),
  integer-literal `ex=`/`cache_ttl` forbidden by
  `tests/unit/test_cache_ttl_source.py`. Golden hashes unchanged.
- [x] OpenSpec proposal `add-asset-reference-store` validated (`--strict`)
  and committed; implementation awaits approval.
- [x] README test count corrected (321, was "197"); empty local fixture
  stub directories removed.
- [x] v4.0 core: enforced application gates, mandatory verified artifact
  metadata, pickle removal, strategy-level holdout, exit-code-2 startup,
  zero-comment code, CI lint/types/tests/coverage/golden/audit/secrets/docker
  jobs, hash-less-lock documented with the `lock-refresh` workflow.
- [x] v3.0 pre-flight items closed during v3.0/v4.0: junk scripts removed,
  deterministic fixtures, expanded docs/ADRs, walk-forward/holdout and model
  lifecycle tests added, `.gitignore` denylist complete.

## Remaining — still true, verified

- [ ] Live execution: no live-exchange adapter exists; paper only. Out of
  scope until a separately reviewed live deployment.
- [ ] `bulk_download` for higher timeframes needs user approval and execution;
  `mtf_data_missing` rejections on thin data are expected until then.
- [ ] Real-data training, real holdout, and the 14-day paper soak are
  user-side via `docs/runbook.md`. The agent never runs network training.
- [ ] `LONG_TERM_CONFIG` thresholds and indicator formulas stay frozen.
- [ ] Hash-pinned `requirements.lock` is blocked: no local Docker, and a
  Windows-built `pip-compile --generate-hashes` would pin wrong-platform
  hashes. Run the `lock-refresh` workflow (workflow_dispatch, Ubuntu), then
  switch the Dockerfile to `--require-hashes`.
- [ ] Proposal `add-asset-reference-store` is unapproved: sections 3.2-3.7 of
  the cache directive must not be implemented until approved.
- [ ] `config.json` is tracked but CLAUDE.md calls it an untracked runtime
  override; it pins `signal_threshold: 10`, which the golden baselines
  silently depend on. Decide: untrack it and make the golden independent of
  it, or document it as tracked tuning.

## New issues for the next phase — in fix order

1. Remove dead `scripts/run_golden.py` (near-duplicate of
   `tests/golden/record_signals.py` with a hardcoded `C:/ME/YujTrade` path)
   and dead `scripts/install_mock.py` (pandas_ta mock nothing imports).
   Evidence: zero references repo-wide outside themselves. Add
   importer-absence tests first, then delete.
2. Remove tracked junk `symtemp.txt` (208-byte stale symbol list from the
   initial commit, referenced nowhere). Same proof-then-delete discipline.
3. Fix the stale `BacktestingEngine` claim in
   `tests/unit/strategy/test_signal_tracker.py` (the engine was deleted in
   v4.0; the docstring still names it the only `resolve()` caller) and audit
   remaining test prose for references to removed code.
4. Remove or wire the four caller-less fetcher methods
   (`get_exchange_info`, `get_all_futures_symbols`, `get_circulating_supply`,
   `get_all_assets` — definition-only matches repo-wide). If exchange
   filters are wanted, that needs its own proposal first.
5. Deduplicate OHLCV caching: `fetch_ohlcv_data` caches per timeframe and
   `_get_higher_tf_data` re-fetches and re-caches the same candles under the
   `mtf_analysis` TTL. Share one entry per symbol/timeframe/limit.
6. Memoize run-level static fetches: without Redis,
   `get_fundamental_data`/`get_onchain_data` hit the network once per
   symbol per timeframe (5x per run). Cache per analysis cycle, not per
   call. Changes fetch timing, so propose before implementing.
7. Sync `sqlite3` in async paths (`SchedulerStore`, `IndicatorHistoryWarehouse`,
   `PaperLedger` hold a blocking connection). Measure loop impact first,
   then migrate behind the same discipline as the asset-reference store.
8. `aiosqlite` is declared in `requirements.txt` but is not installed, not
   pinned in `requirements.lock`, and imported nowhere. Pin or drop it
   before anything depends on it.
9. Naive `datetime.now()` in the Telegram date line
   (`app/telegram_bot.py` display string) — use timezone-aware UTC.

## Legacy tracked artifacts (resolved in v3.0, still true)

- `models/` untracked via `git rm --cached` (files stay on disk);
  `/models/` is gitignored. No default-marker test and no `ModelManager`
  predict path depends on it.
- `calibration.json` was never tracked; gitignored, stays untracked.
- `*.db` under `runs/` are runtime-only, untracked and ignored.

## Out of scope (user-side)

- [ ] Move `ENCRYPTION_PASSWORD` to `SECRET_ENCRYPTION_PASSWORD` env var (user).
- [ ] Physical reshuffle into `infrastructure/` (future work).
- [ ] Organization secret manager adoption (future work).
- [ ] Live execution enablement (future work, requires `execution_dry_run` review).
- [ ] `docker-compose.yml` stays absent; compose-based deployment is user-side.
