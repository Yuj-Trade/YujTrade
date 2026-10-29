# Phased implementation log (2026-10-29)

Implements YT-IMPL-SPEC Revision 2.0 (`YujTrade: Phased Implementation
Specification`) on `main`, phases P0 to P10. One concern per commit, each
phase closed with its evidence here.

## P0 — preflight and baseline

### Environment

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD at start | `d7e57d3878a259184484932bbfb0ac9667bc49b2` |
| Python | `3.13.15` |
| Working tree | clean (`git status --short` empty) |
| Toolchain | `pip freeze` in `runs/implementation/env.txt` (gitignored) |

### Preflight checks (spec step 2, finding F23)

| Path | Present |
|---|---|
| `openspec/` | yes |
| `openspec/AGENTS.md` | yes |
| `tests/fixtures/` | yes (5 CSV fixtures) |
| `.github/` | yes |
| `docs/implementation-log.md` | no (created by this phase) |

No gap found; no slow check is blocked by a missing tree.

### Baseline gate (spec step 5)

| Gate | Command | Result |
|---|---|---|
| Default | `python -m pytest -m "not slow and not ml" -q` | 1865 passed, 13 skipped, 11 deselected, 0 failed |
| Slow | `python -m pytest -m slow -q` | 11 passed |
| Lint | `ruff check .` | pass |
| Format | `ruff format --check .` | pass (273 files) |
| Types | `mypy domain` | pass (9 files) |
| Coverage | `--cov=domain --cov-fail-under=90` | 97.80 % |

Baseline is green, so `docs/open_issues.md` receives no pre-existing failure
list.

Golden SHA-256 at the baseline (frozen for the whole run, decision G2):

```
d17e604f011a94909796c907321eafb9bd2558e07b50f3d3e5d4e1b4a9c6a512  tests/golden/backtest_baseline.json
8f7173b71a7cb9bf503a4363542f7319425a3717d0296239d25088d0d75d265a  tests/golden/signals_baseline.json
```

The same values are recorded in `tests/golden/golden.sha256`. Full machine
record: `runs/implementation/baseline.json` (gitignored).

### Identifier verification (spec step 3, Appendix C)

Every Appendix C identifier resolved in the working tree. Signals that confirm
the findings the later phases depend on:

| Check | Command | Result | Confirms |
|---|---|---|---|
| Paper engine entry points | `rg -F fill_order` / `apply_funding` / `resolve_position_with_candles` | 1 file each | F1, F2, F18 |
| Paper path caller | `rg -n "paper_command\|execute_signal" app/telegram_bot.py` | `execute_signal` called at line 285, no definition in `services/` | F18 |
| Count-based windows | `rg -n "_resolve_signal_outcome\|_watch_group" services/trading_service.py` | definitions at 634 and 678 | F7 |
| Watch loop gate | `rg -n "_outcome_watch_loop" main.py` | started only under `if policy.enabled` | F8 |
| Learner notifications | `rg -n "alert\|notify" modeling/learner.py` | none | F9 |
| Golden recorder signature | `cat scripts/record_backtest.py` | no CLI, no arguments | F16 |
| Architecture test path | `tests/unit/test_architecture.py` | present (F22 path was `test_migration_contracts.py`) | F22 |

No mismatch was found. Appendix C row `tests/unit/domain/test_migration_contracts.py`
for F22 also resolves.

### Proposals

Seven OpenSpec changes created under `openspec/changes/`, approved by G1:

| Change id | Scope |
|---|---|
| `add-cost-model-v2` | item 1 (cost model) |
| `add-time-range-ohlcv-fetch` | item 6 (time-range fetch) |
| `add-paper-execution-path` | prerequisite (F18) |
| `unify-performance-metrics` | item 2 (one metrics source) |
| `add-feature-store` | item 3 (feature store) |
| `add-learning-alerts` | item 4 (learning alerts) |
| `add-intrabar-outcome-port` | item 5 (intrabar port) |

Each passes `openspec validate <id> --strict`.

## P1 - pure cost foundation

| Item | Result |
|---|---|
| Commit | `4960f7b chore: add pure cost profile and fill model in domain` |
| Files | `domain/costs.py` (new), `domain/performance.py`, `tests/unit/domain/test_costs.py` (new) |
| Gate | default 1899 passed; ruff, format, `mypy domain` pass; domain coverage 96.83 % |
| Golden | unchanged (`d17e604f...`, `8f7173b7...`) |
| Tag | none (no existing test changed) |

`net_r_multiple` keeps its signature and delegates to `net_r` with
`legacy_report_profile(fee_rate, slippage_rate)` and `fill_ratio = 1.0`. The
200-record seeded equivalence test pins the legacy profile to the previous
formula to a relative error below `1e-12`.

## P2 - time-range candle fetch [behavior-change]

| Item | Result |
|---|---|
| Commit | `870d0c4 fix: fetch outcome candles by time range [behavior-change]` |
| Files | `data/data_provider.py`, `data/sources/binance_fetcher.py`, `services/trading_service.py`, `tests/unit/data/test_ohlcv_range.py` (new), 6 service test files |
| Tests | 11 new range tests; the service tests now exercise the range call |
| Gate | default 1913 passed; slow 11 passed; ruff, format, `mypy domain` pass |
| Golden | unchanged (`d17e604f...`, `8f7173b7...`) |
| Behavior change | `_resolve_signal_outcome` takes a keyword-only `now` and fetches the expiry window by range; `_watch_group` fetches `[oldest, now]` by range. An empty window before the window end stays pending; at or after the window end it resolves to `no_data`. |
| Test call sites updated | `tests/unit/services/test_reconciliation_resolution.py` (provider fake and `now`), `test_service_delegation.py` (provider fake and `now`), `test_outcome_watch.py` (range fake), `test_reconciliation_ledger_wiring.py` and `test_cycle_observability.py` (fake resolver signature), `test_outcome_dispatch.py` (range fake) |

Issues 10 and 17 are resolved in `docs/open_issues.md`; the superseded
ADR-0009 bullet carries a pointer to `870d0c4`.

## P3 - cost-model-v2 in the paper engine and the report [behavior-change]

| Item | Result |
|---|---|
| Commit 1 | `6d66942 chore: add entry_quote_volume column to signal resolutions` |
| Commit 2 | `b57a571 fix: apply cost-model-v2 to paper engine and performance report [behavior-change]` |
| Commit 3 | `43417c3 docs: add performance worked example v2 and log phase P3` |
| Files | `domain/costs.py` (used), `domain/performance.py`, `domain/outcome.py`, `trading/ledger.py`, `trading/paper_trading.py`, `application/performance_report.py`, `services/trading_service.py`, `config/settings.py` |
| Tests | `tests/unit/trading/test_paper_cost_model_v2.py` (new, 19), `tests/unit/application/test_performance_worked_example_v2.py` (new, 9), 4 migration cases in `test_resolution_ledger.py` |
| Gate | default 1947 passed; ruff, format, `mypy domain` pass |
| Golden | unchanged (`d17e604f...`, `8f7173b7...`) |

### Migration

`runs/paper_ledger.db` does not exist on this machine, so no backup was
needed. The migration is idempotent: `PRAGMA table_info(signal_resolutions)`
gates the `ALTER TABLE ... ADD COLUMN entry_quote_volume REAL`; the triggers
and the CHECK constraints are untouched; an old row reads back with `NULL`
and is treated as a full fill.

On an operator machine the backup is taken before the first run of the new
code (`runs/backup/paper_ledger-<UTC timestamp>.db`); the runbook records
the step.

### Behavior change listed for the final report

- The report is `performance-report-v2`; the parameter block carries the
  whole cost profile; the report gains `coverage`, `equity_source` and
  `legacy_resolutions_note`.
- The data hash now covers `entry_quote_volume`, so existing report hashes
  change once (expected; recorded here).
- The paper engine now follows `SIGNAL_EXPIRY_BY_TIMEFRAME` when it resolves
  a position (it previously used the barrier-only `resolve_outcome` and never
  expired a position).
- `apply_funding` and `funding_rate_per_day` are removed.

### Deviation

The spec says a fill fraction of `0.0` means "the order does not fill". With
the formula `min(1, p * quote_volume / notional)` that only happens at a zero
quote volume; a dust volume (for example `1.0`) yields a positive but tiny
fraction and the trade stays in the statistics. The implementation keeps the
formula exactly as specified, and the test pins both cases.

## P4 - paper execution path restored [behavior-change]

| Item | Result |
|---|---|
| Commit | `abc1af6 fix: restore paper execution path behind paper_execution_enabled [behavior-change]` |
| Files | `services/trading_service.py`, `trading/ledger.py`, `app/telegram_bot.py`, `main.py`, `config/settings.py` |
| Tests | `tests/unit/services/test_paper_execution.py` (new, 12), `tests/unit/trading/test_paper_execution_guard.py` (new, 5), `test_command_guards.py` isolation case |
| Gate | default 1965 passed; slow 11 passed; ruff, format, `mypy domain`; `test_no_withdraw_calls.py` passes |
| Golden | unchanged (`d17e604f...`, `8f7173b7...`) |

### Contract as implemented

- `execute_signal` refuses `unsupported_mode`, `paper_execution_disabled`,
  `duplicate_signal`, `no_mark_price`, `risk_rejected` and `unfilled`
  without raising.
- The duplicate guard reads `orders` through `PaperLedger.has_order`, so it
  survives a restart.
- The mark price is the last closed candle (open time + duration at or
  before now); the quote volume is that candle's volume times its close.
- `paper_positions_opened` / `paper_positions_closed` are append-only;
  `load_open_positions` is opened minus closed, and
  `rehydrate_paper_positions` runs inside `TradingService.initialize()`.
- `_paper_resolution_loop` runs when `paper_execution_enabled` is true and
  does not depend on the outcome notification policy (F8).
- The AST guard proves no paper module and no paper entrypoint reaches
  `trading/exchanges/`, `ExchangeAdapter` or `ExecutionEngine`; the exchange
  wiring stays inside `_build_exchange_service` and the `ExchangeExecutionService`
  construction, which are a separate concern of the same module.

### Additional operator-visible change (not in the spec)

`TradingService.portfolio_snapshot()` is added because `/portfolio` also
called a missing method; it returns the live `PortfolioManager` snapshot
with the mark prices. It is outside the six items and is reported here and
in the final report.

### Test helper note

`tests/unit/app/test_command_guards.py` is updated (existing test kept
intact) with a new isolation case; the original
`test_paper_command_rejects_non_admin` body was accidentally deleted by an
edit and restored verbatim in the same commit.
