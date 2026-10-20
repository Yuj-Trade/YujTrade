# Paper performance soak — checklist

The fourteen-day paper soak runs on the operator's machine because it
needs the network, the live market data and a real paper session. The
agent prepares the tooling and the checks; the operator runs them.

- Tooling: `scripts/compare_ledger_and_tracker.py` and
  `scripts/generate_performance_report.py`.
- Runbook: `docs/runbook.md`, section 10.
- Definitions: `docs/adr/ADR-0009-performance-metrics.md`.
- Worked example: `docs/performance-worked-example.md`.

## Before the soak

- [ ] `python -m pytest -m "not slow and not ml" -q` is green.
- [ ] `ruff check .` and `ruff format --check .` are green.
- [ ] `mypy domain` is green.
- [ ] `python main.py` starts, `/health` answers and the log shows
      `Reconciled N expired pending signal(s).` at least once.
- [ ] `performance_ledger_enabled` is `false` in `ConfigManager.DEFAULT_CONFIG`
      and the local `config.json` does not override it yet.

## Every day

- [ ] `python scripts/compare_ledger_and_tracker.py` exits 0.
- [ ] The reported `no_data` ratio stays below 5 %.
- [ ] The ledger row count never decreases.
- [ ] `/performance` shows the expected numbers and a `data_hash` that only
      changes when the data changes.
- [ ] `python scripts/generate_performance_report.py --as-of <today>` writes
      `runs/performance/performance-report.json`.

## Day 14 — the acceptance criteria

| # | Criterion | How it is checked | Result |
|---|---|---|---|
| a | the number of new tracker resolutions equals the number of new ledger rows plus the recorded `no_data` rows | `scripts/compare_ledger_and_tracker.py` | |
| b | the `no_data` ratio is below 5 % | the same script; a higher ratio means the reconciliation cadence is too coarse for the expiry window and the cause is recorded in `docs/open_issues.md` | |
| c | two report runs over the same data produce the same `data_hash` | `python scripts/generate_performance_report.py` twice with the same `--as-of` | |
| d | no deletion and no pruning happened on the ledger | the row count of the previous snapshot in the same script, plus the append-only triggers | |
| e | the JSON report contains no `NaN` and no `inf` | `grep -i "nan\|infinity" runs/performance/performance-report.json` returns nothing | |
| f | the independent calculator agrees below `1e-9` | `tests/unit/application/test_performance_determinism.py` | |

## After the acceptance

- [ ] Set `performance_ledger_enabled` to `true` in the **local**
      `config.json` only. The committed default stays `false`.
- [ ] Record the outcome in `docs/open_issues.md`: the observed `no_data`
      ratio, the reconciliation cadence and the number of tracked signals.
- [ ] Decide about the holdout Sharpe divergence (open issue 12): propose a
      separate change or accept the two definitions.
