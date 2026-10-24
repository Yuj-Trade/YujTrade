# Open Issues Register

Status as of 2026-10-20 (Phases 0-2 of IMPROVEMENT_REPORT.md delivered,
Phase 3 model lifecycle in progress, verified locally).
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
- [x] `config.json` contradiction resolved: untracked in `98bcc57`
  (file removed from the index, stays on disk, `.gitignore:194` intact).
  Golden independence is proven by
  `tests/unit/common/test_config_json_independence.py` (defaults identical
  with and without the legacy override) and untracked status is enforced by
  `tests/unit/scripts/test_dead_code_guard.py::test_config_json_stays_untracked`.
- [x] `aiosqlite==0.22.1` is pinned in `requirements.lock` and imported by
  the async stores; the "declared but unpinned" entry was stale.
- [x] Naive `datetime.now()` replaced with timezone-aware
  `datetime.now(UTC)` in `app/telegram_bot.py:397`.
- [x] `backtrader` removed from `requirements.txt` (never imported by any
  tracked production module); enforced by
  `tests/unit/scripts/test_dead_code_guard.py::test_backtrader_neither_declared_nor_imported`.
- [x] Phase 1 (architecture & I/O): `PaperLedger` migrated to `aiosqlite`
  with the append-only and unique-`signal_id` contract preserved; run-scoped
  external-data memoization collapses one upstream call per datum per cycle.
- [x] Phase 2 (signal quality & observability): `signal_history.json` is
  TTL-bounded and rotates, `AdaptiveThresholdManager` state survives a
  restart, replayed cycles are idempotent, and every lifecycle transition
  carries correlation IDs and metrics.
- [x] Phase 3 (model lifecycle): feature-drift detection
  (`modeling/drift.py`), warm-start retraining, guarded promotion with
  automatic rollback (`modeling/promotion.py`), a training CLI with
  `--dry-run`/`--warm-start`/`--data`, a versioned Monte-Carlo block in the
  holdout report, a walk-forward validation job, and a prediction-time
  feature trace. Rationale in `docs/adr/ADR-0008-model-lifecycle.md`.
- [x] Training corrupted the promoted artifact. A model resolves its file
  paths from its own `model_path`, and `ModelManager.get_model` points that
  path at the promoted artifact directory so the model can be loaded from it.
  `fit()` then saved the new weights *into the promoted version directory*,
  invalidating its recorded `files_sha256` and making the promoted artifact
  fail `verify_current` on the next load. Training now writes to a staging
  directory and the registry copies the staged files into the new version; a
  non-promoted candidate is also evicted from the in-memory cache so the next
  prediction reloads the promoted artifact. Enforced by
  `tests/unit/modeling/test_training_isolation.py` (7 tests).
- [ ] Golden baselines are not byte-reproducible on every machine. The
  determinism test fails on a clean checkout of `main` (verified by stashing
  the Phase 3 work: the same test fails without it). The drift is ULP-level
  in `confidence_score` only — 59 signals, 15 trades and every other field
  are identical — and TensorFlow reports "oneDNN custom operations are on.
  You may see slightly different numerical results due to floating-point
  round-off errors from different computation orders". The committed
  baseline was recorded on a different TensorFlow build. `TF_ENABLE_ONEDNN_OPTS=0`
  changes the recorded values again (53 differing lines instead of 49), so it
  is not a fix. Do not re-record the baseline from a single workstation;
  re-record in the Linux CI image, or pin the TensorFlow build used for the
  original recording, and keep the hash check as the gate.

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
   (Warehouse + SchedulerStore + `PaperLedger` are migrated — see
   IMPROVEMENT_REPORT.md Phase 1.)
8. Feature store for training reuse. The Phase 3 prediction trace records
   what the model saw at prediction time; a store that training can consume
   needs its own OpenSpec proposal (`add-feature-store`) before it is built.
9. Performance report — legacy resolutions. Signals that the tracker resolved
   with the pre-phase-3 logic (the current-price fallback) are not written to
   `signal_resolutions` and are therefore not part of the report. The report
   only covers resolutions recorded from the phase-3 resolution path onwards.
   Backfilling them would require re-running the old fallback, which is
   exactly the non-reproducible behaviour this work removed.
10. Performance report — data provider windowing. `fetch_ohlcv_data` only
    accepts a candle *count*, not a time range, so the resolver asks for
    `ceil(expiry / candle_duration) + 2` candles and then verifies the
    coverage itself. A signal that is reconciled later than its expiry can
    therefore fail the coverage check and resolve to `no_data`. A time-range
    fetch in `data/data_provider.py` would remove the limit; that is a data
    contract change and needs its own proposal.
11. Performance report — the `1M` candle duration is a fixed 43200 minutes
    (30 days) because a calendar month has no fixed length. The coverage
    check for a monthly signal is therefore approximate. A per-month
    duration derived from the candle timestamps themselves would remove the
    approximation.
12. Sharpe in `scripts/run_holdout.py` is a different quantity from the
    report Sharpe: it divides the mean pnl by `pstdev(pnl)` and multiplies by
    the square root of the trade count, with no annualisation and no
    risk-free rate. The holdout report schema is locked and the holdout
    protocol is single-use, so the holdout path is left untouched. Unifying
    the two definitions needs its own proposal.
13. The report equity curve is a model, not the paper portfolio. It
    compounds fixed fractions of the equity, while `PaperTradingEngine`
    sizes its positions with the risk model and the portfolio exposure cap
    and keeps the positions in the `PortfolioManager`. The two are
    deliberately not reconciled in this phase; a reconciliation needs a
    proposal because it changes the meaning of the reported equity.
14. The reported cost model is flat per trade: no partial fill, no funding
    cost, no maker/taker distinction and no slippage model beyond the
    constant rate. The paper engine uses the same two rates, so the report
    and the paper engine agree on the cost, but neither models the fill.
15. The outcome notification is only raised on a **closed** candle, so the
    inherent delay is the duration of the candle plus the watch interval.
    A target that is touched inside a one-hour candle is reported after
    that candle closes, and a `1d` signal is reported up to a day later.
    An intrabar feed would remove the delay, but the data provider does
    not offer one. See `docs/adr/ADR-0010-signal-outcome-notifications.md`.
16. `app/tasks.py` and the `TaskServiceContainer` build a second stack and
    a second `SignalTracker` over the same `signal_history.json`. They must
    never run at the same time as the main tracker: the two trackers would
    overwrite each other's history and the notification state. `app/tasks.py`
    is not wired to the outcome watch loop.
17. The outcome watch fetches the candles with a **count**, not a time
    range, like the resolution path (see open issue 10). A signal that is
    observed long after its creation may not find a covered window and is
    then not observed at all. A time-range fetch in
    `data/data_provider.py` would remove the limit and is a data contract
    change that needs its own proposal.

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

## app.log remediation 2026-10-22 - resolved

Evidence: `docs/remediation/app-log-2026-10-22.md`. Baseline tag
`pre-applog-remediation`.

- [x] E01 CryptoPanic `auth_token` printed in plain text: redacted by a loguru
  patcher in `config/logger.py`. `113b299`.
- [x] E16 Full Cloudflare HTML logged: error bodies are tag-stripped and capped
  at 200 characters. `6cb8261`.
- [x] E14 (config part) `diagnose=True` would print locals: file sink options
  moved to `FILE_SINK_OPTIONS` with `diagnose=False`. `e85e7ff`.
- [x] E04 `database is locked`: WAL, 30 s busy timeout, per-instance lock in
  `IndicatorHistoryWarehouse`. Reproduced at 200 concurrent tasks before the
  fix. `6bf4842`.
- [x] E02 CoinGecko 10011: endpoint and credential now selected by
  `coingecko_api_tier`. `a7ba02b`.
- [x] E03 CoinGecko circuit breaker: consequence of E02, no separate change.
- [x] E05, E07, E12 Upstream timeouts and 403s now raise
  `UpstreamUnavailableError` and count toward the breaker. `00a67f0`.
- [x] E08 DeFiLlama `Protocol not found`: `/v2/chains` verified live (HTTP 200,
  421 chains). `1daec0c`.
- [x] E11 `Source coindesk failed` for unsupported symbols: CoinDesk is only
  added for BTC and ETH. `cf3f3cf`.
- [x] E10 CoinDesk not-found swallowed at DEBUG: now a WARNING with status and
  body. `facfd17`.
- [x] E09 `api.coindesk.com` DNS failures: CoinDesk news gated behind
  `coindesk_news_enabled`, default off. Host confirmed non-resolving. `df5eb2e`.
- [x] E14 tracebacks absent: 49 `exc_info` sites converted to
  `logger.opt(exception=...)`, and the file sink format now includes
  `{exception}`. `0a896be`, `1803d52`.
- [x] E15 Analysis failure without symbol or timeframe: `analyze_symbol` now
  logs both and re-raises. `ee16a14`.

## app.log remediation 2026-10-22 - open

- [ ] U1 Rotate the CryptoPanic key. It was printed in `logs/app.log`. Rotate at
  the provider, re-encrypt with `python scripts/encrypt_keys.py`, and delete old
  log copies. User-side.
- [ ] U2 Redis host. `getaddrinfo failed` (code 11001) means the configured host
  does not resolve. Copy the current host and password from the Redis Cloud
  dashboard into `.env`. User-side.
- [ ] U3 Binance futures reachability. `fapi.binance.com` timed out for every
  symbol while spot succeeded. Test from the runtime machine; if it fails,
  derivatives data is unavailable on this network. User-side.
- [ ] U5 CoinDesk host. `api.coindesk.com` does not resolve (verified
  2026-10-23). CoinDesk news stays disabled until it does.
- [ ] U6 CryptoPanic access. Cloudflare returned 403 for every request. Confirm
  the provider account allows API access from this network.
- [ ] E06 Messari 404s: BLOCKED, not fixed. On 2026-10-23 `data.messari.io`
  returned 404 for the API root and for every candidate slug including
  `bitcoin`, so the ticker-to-slug theory could not be verified and no mapping
  was written. Needs confirmation that a Messari plan is active and what the
  current base URL is.
- [ ] `messari_asset_slugs` config key is declared but unpopulated, pending E06.
- [ ] CoinDesk OHLCV endpoint (`spot/v1/historical/ohlcv`) could not be verified
  because the host does not resolve. Path and parameters are unchanged and
  unverified.
- [ ] `get_latest_news` and `get_bitcoin_price_index` in
  `data/sources/coindesk_fetcher.py` are unreferenced by runtime code.
- [ ] `PaperLedger` and `SchedulerStore` still open a connection per call and do
  not use WAL. Same class of risk as E04, not yet fixed.

## Post-run verification 2026-10-23 - resolved

- [x] Binance futures breaker no longer blocks spot: separate
  `futures_circuit_breaker`. `a03cc85`.
- [x] Tracebacks start on their own line in the file sink. `dd076f0`.
- [x] CoinDesk OHLCV endpoint corrected to `spot/v1/historical/{days|hours}`,
  verified live with HTTP 200 and real candles for BTC 1h and ETH 1d. `5050bce`.
- [x] `decorrelation_disabled` logged at DEBUG; the warehouse was verified
  healthy (45,794 rows). `f0a5091`.
- [x] Messari gated behind `messari_enabled` (default off). `34f999c`.

## Post-run verification 2026-10-23 - open

- [ ] E06 Messari: root cause is now known and is not a code bug.
  `api.messari.io/metrics/v1` returns HTTP 401 "A Messari Enterprise membership
  is required" with the configured key. `data.messari.io/api/v1` is retired
  (404). To restore on-chain metrics, an Enterprise plan is required; then set
  `messari_enabled` to true and update `base_url` to
  `https://api.messari.io/metrics/v1`. The ticker-to-slug mapping was never the
  problem and no slug map is needed for the metrics path.
- [ ] `messari_asset_slugs` config key remains declared but unused; it may be
  removable once the Messari path is settled.
- [ ] CoinDesk `hours` endpoint returned HTTP 429 (rate limit exceeded) during
  probing while `days` succeeded. The 1h path works through the same endpoint
  family but the account tier may cap hourly history. Watch for 429 on
  `historical/hours` in the next run.
- [ ] `modeling/models.py` constructs `FeatureEngineer()` without a history
  provider, so decorrelation is always disabled on the ML path. Not a bug, but
  the ML features never get correlation weighting.
