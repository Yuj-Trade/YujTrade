# Tasks: add-paper-performance-report

## 0. Proposal

- [x] 0.1 Verify the review findings against the repository (tracker
      pruning/rotation, current-price fallback, fixed candle limit, boolean
      outcome only, triple cost model, unused `PaperLedger` in production,
      three unused metric helpers, divergent holdout Sharpe, `initial_cash`
      and `risk_per_trade_pct` outside `DEFAULT_CONFIG`)
- [x] 0.2 Write `proposal.md` with the owner decisions, the default
      definitions, the data contracts, the configuration keys, the schema
      change, the file list, the risks and the rollback plan
- [x] 0.3 Write `specs/performance-report/spec.md`
- [x] 0.4 `openspec validate add-paper-performance-report --strict` is green
- [x] 0.5 Commit the proposal with the `docs:` prefix

## 1. Characterize the current behaviour

- [ ] 1.1 Characterization test locking the `total`, `win_rate` and
      `pending` keys of `SignalTracker.get_performance_summary`
- [ ] 1.2 Characterization test showing that the current reconciliation path
      falls back to the current market price, marked as intentionally changed
      in phase 3
- [ ] 1.3 Status-register test showing that the three `common/utils.py`
      metric helpers are defined and have no caller
- [ ] 1.4 Status-register test showing that `PaperLedger` is not imported by
      production code
- [ ] 1.5 Status-register test showing the hard-coded `fee_rate` and
      `slippage_rate` defaults of `PaperTradingEngine`
- [ ] 1.6 No production change; the default gate stays green and the golden
      hashes are unchanged

## 2. Append-only resolution ledger

- [ ] 2.1 `domain/performance.py`: `ResolutionRecord` with the section 4.5
      fields and the validation rules
- [ ] 2.2 `trading/ledger.py`: `signal_resolutions` table with the `CHECK`
      constraints and the append-only triggers
- [ ] 2.3 `PaperLedger.record_resolution` returns `False` on a duplicate
      `signal_id` and lets every other error, including a `CHECK` violation,
      propagate
- [ ] 2.4 `PaperLedger.has_resolution` and
      `PaperLedger.load_resolutions(start_utc, end_utc)` ordered by
      `(exit_at_utc, signal_id)`
- [ ] 2.5 `tests/unit/trading/test_resolution_ledger.py`: insert, duplicate,
      timestamp format, `no_data` with `NULL`, rejected `UPDATE`/`DELETE`,
      raised `CHECK` error, idempotent `initialize`, orders unaffected
- [ ] 2.6 The default gate is green; `test_ledger.py` and
      `test_ledger_parity.py` stay green

## 3. Full-coverage resolution and ledger wiring `[behavior-change]`

- [ ] 3.1 `domain/outcome.py`: a pure resolution function with explicit
      coverage; `resolve_outcome` stays unchanged
- [ ] 3.2 `services/trading_service.py`: request the candle count derived
      from the expiry and the candle duration
- [ ] 3.3 Remove the current-price fallback and the now unused
      `_get_reference_price`
- [ ] 3.4 Reconciliation order: resolve, skip when a resolution already
      exists, otherwise record, and on a ledger error log and keep the signal
      pending
- [ ] 3.5 Tracker synchronisation: the old boolean outcome for `stop`,
      `target` and `expired`; `no_data` writes `resolution_status` only
- [ ] 3.6 `get_pending_expired` skips `no_data` entries;
      `get_performance_summary` keeps its keys and adds the `no_data` count
- [ ] 3.7 `_record_live_calibration` is called for boolean outcomes only
- [ ] 3.8 Tests: `tests/unit/domain/test_outcome_edges.py`,
      `tests/unit/trading/test_ledger_parity.py`,
      `tests/unit/strategy/test_signal_tracker.py` and the service tests for
      the write order, the continue-after-error and the absence of the
      current price
- [ ] 3.9 The golden hashes are unchanged; `docs/open_issues.md` records the
      pre-phase-3 resolutions

## 4. Pure metric primitives

- [ ] 4.1 `domain/performance.py`: net R multiple, fixed-fraction return,
      equity curve, daily returns, MDD with all fields, Sharpe, Sortino, win
      rate, profit factor, expectancy
- [ ] 4.2 Standard library only, no `now()`, no I/O; `NaN`/`inf` inputs raise
      `ValueError`; undefined results are `None`
- [ ] 4.3 `tests/unit/domain/test_performance.py` with hand-checkable values
      and the edge cases: empty, single, all wins, all losses, zero spread,
      no downside, input order, idle days, invalid input
- [ ] 4.4 `mypy domain` is green, the domain coverage is at least 90% and
      `ruff` is green

## 5. Application report

- [ ] 5.1 `application/performance_report.py`: `PerformanceConfig`,
      `PerformanceReport` and the builder
- [ ] 5.2 `data_hash` over the canonical JSON of the included records
      (including `no_data`), `config_hash` over the effective parameters
- [ ] 5.3 `tests/unit/application/test_performance_report.py`: no trade, only
      `no_data`, one trade, below the minimum sample, order stability, a
      changed record changes the hash, no `NaN`/`inf` in the JSON

## 6. Wiring

- [ ] 6.1 The performance keys in `ConfigManager.DEFAULT_CONFIG`
- [ ] 6.2 `PaperTradingEngine` takes `fee_rate` and `slippage_rate` from the
      configuration; the hard-coded constructor defaults are removed
- [ ] 6.3 `TradingService` owns a `PaperLedger` and exposes
      `build_performance_report(as_of)`; `create_trading_stack` keeps its
      signature
- [ ] 6.4 `/performance` shows the new numbers through `escape_markdown_v2`
      and stays below 4096 characters
- [ ] 6.5 `scripts/generate_performance_report.py` writes
      `runs/performance/<name>.json` and prints the `data_hash`
- [ ] 6.6 The default gate is green; `test_config_json_independence.py` and
      `test_service_delegation.py` stay green

## 7. Verifiability

- [ ] 7.1 Determinism test: two report builds over the same ledger produce
      the same `data_hash` and the same fields; one changed exit changes the
      hash
- [ ] 7.2 Independent recomputation in `tests/` that recomputes Sharpe,
      Sortino, MDD and the equity curve from the ledger output without
      importing `domain/performance` or `application`; the relative
      difference is below `1e-9`
- [ ] 7.3 `docs/performance-worked-example.md` with three trades (target,
      stop, expired) and the step-by-step numbers
- [ ] 7.4 `docs/adr/ADR-0009-performance-metrics.md` with the definitions, the
      decisions and the limitations
- [ ] 7.5 `python -m pytest -m slow -q` and the golden hashes equal the
      baseline

## 8. Integration and dead-code removal

- [ ] 8.1 The importer-absence test for the three `common/utils.py` helpers
      is green, then the helpers are deleted
- [ ] 8.2 `tests/unit/scripts/test_dead_code_guard.py` is updated
- [ ] 8.3 `scripts/run_holdout.py` is untouched; `docs/open_issues.md`
      registers the Sharpe divergence and suggests a separate proposal
- [ ] 8.4 `docs/runbook.md`: reading the report, the configuration keys, the
      daily controls
- [ ] 8.5 `docs/architecture.md`: the new ledger, domain and application flow
- [ ] 8.6 `docs/open_issues.md`: the bounded list of open limitations
- [ ] 8.7 `docs/exceptions_audit.md` is updated for the new handlers

## 9. Operational acceptance

- [ ] 9.1 The 14-day paper soak runs on the operator's machine
- [ ] 9.2 The ledger/tracker comparison script and the acceptance checklist
      exist
- [ ] 9.3 `performance_ledger_enabled` is set in the local configuration
      only, never in the committed defaults
