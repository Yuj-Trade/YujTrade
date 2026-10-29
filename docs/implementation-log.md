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
