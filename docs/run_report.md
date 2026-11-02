# Run report: exchange connectivity

Phases 0 to 13 of the exchange connectivity playbook, executed in one pass on
`main`. No branch, worktree, tag or stash was created. Every commit was made
after the gate of section 19.1 was green.

## Baseline (recorded before any change)

| Gate | Result |
|---|---|
| `python -m pytest -m "not slow and not ml" -q` | 1648 passed, 10 skipped, 11 deselected |
| `ruff check .` | clean |
| `ruff format --check .` | clean (239 files) |
| `mypy domain` | clean |

Golden hashes at baseline (SHA-256):

```text
d17e604f011a94909796c907321eafb9bd2558e07b50f3d3e5d4e1b4a9c6a512  tests/golden/backtest_baseline.json
8f7173b71a7cb9bf503a4363542f7319425a3717d0296239d25088d0d75d265a  tests/golden/signals_baseline.json
```
## Final commit list on main

| Commit | Message |
|---|---|
| f23ba3c | docs(openspec): add exchange connectivity proposal, ADR-0011, ADR-0012 and runbook |
| e2664fc | fix(exchange): fail closed in ExchangeAdapter [behavior-change] |
| fb574de | feat(exchange): add domain types, ports, policy and registry [behavior-change] |
| 997f048 | feat(exchange): encrypted credential loading for exchange secrets [behavior-change] |
| bd90b3e | feat(exchange): read-only ccxt market data gateway and probe script |
| 6104940 | feat(exchange): authenticated read-only queries and key permission check |
| ed32afc | feat(exchange): live ledger and reconciliation without order placement |
| fb2e086 | feat(exchange): sandbox order submission with gate and risk checks [behavior-change] |
| c7147ed | feat(exchange): admin telegram controls for exchange status, execution and halt [behavior-change] |
| f4a3237 | feat(exchange): shadow mode and shadow report |
| 00fa696 | feat(exchange): live gate confirmation flow and activation checklist [behavior-change] |
| 31ddeb6 | docs(exchange): probe results table and sandbox facts |
| aefb305 | test(exchange): iran profile scoping and ourbit documentation template |
| 2cdf11f | feat(exchange): exchange metrics and architecture notes |

## Final gate

| Gate | Result |
|---|---|
| ``python -m pytest -m "not slow and not ml" -q`` | 1865 passed, 13 skipped, 11 deselected |
| ``ruff check .`` | clean |
| ``ruff format --check .`` | clean (273 files) |
| ``mypy domain`` | clean |
| ``git diff --check`` | clean |
| Golden hashes | identical to baseline |
| ``git branch --list`` | ``main`` plus a pre-existing ``baseline/pre-agent`` that was present before this run |

Golden hashes at the end (must equal baseline):

``````text
d17e604f011a94909796c907321eafb9bd2558e07b50f3d3e5d4e1b4a9c6a512  tests/golden/backtest_baseline.json
8f7173b71a7cb9bf503a4363542f7319425a3717d0296239d25088d0d75d265a  tests/golden/signals_baseline.json
``````

## Push status

``git push origin main`` was not run. ``git ls-remote --heads origin`` shows
``origin/main`` at ``945ce7a`` while the local ``main`` carries the 14 commits
above, so the push is a fast-forward that the operator should confirm and run.
Recorded as blocked in this report rather than retried.

## Phase status

Status reflects the connectivity review of 2026-10-29. Phases 6, 7, 8 and 10 were
not functional as delivered; see
`docs/remediation/exchange-remediation-2026-10-29.md`.

| Phase | Status |
|---|---|
| 0. Governance | partial (ADR accepted without confirmation; corrected to proposed) |
| 1. Baseline and adapter fixes | done |
| 2. Domain, ports, policy, registry | done |
| 3. Encrypted secrets | done |
| 4. Read-only market data | done (network probe `blocked_by_operator`) |
| 5. Authenticated reads and permission check | done (LBank rule `blocked_by_operator`) |
| 6. Live ledger and reconciliation | partial (no schema init, no run loop; fixed in R3 and R5) |
| 7. Sandbox submission | partial (sizing broken; fixed in R6) |
| 8. Telegram controls | partial (halt failed, execute refused; fixed in R3 and R6) |
| 9. Shadow mode | done (14-day soak `blocked_by_operator`) |
| 10. Live activation mechanism | partial (confirmation not wired; fixed in R8) |
| 11. Further general venues | done as code + documented procedure (probe `blocked_by_operator`) |
| 12. Iran profile | done for LBank; Ourbit `blocked_by_operator` |
| 13. Operations | done |

## Remediation of 2026-10-29

`docs/remediation/exchange-remediation-2026-10-29.md` records R0 to R14. Each
finding from `yujtrade_exchange_connectivity_review.md` is either fixed with
its commit or left open with a reason in `docs/open_issues.md`.

## Verified environment findings

The pinned `ccxt==4.5.90` was inspected before use. Findings that changed the
registry or the plan are documented in
`docs/adr/ADR-0011-exchange-connectivity.md`:

- `lbank2` does not exist; `lbank` is the v2 client.
- `lbank` permission endpoint is `supplement/api_Restrictions`.
- `kucoin` `set_sandbox_mode(True)` raises `TypeError` in this version.

## Known limitations

- `TradingService.execute_signal` and `TradingService.portfolio_snapshot` are
  referenced by `app/telegram_bot.py` and the app tests but were absent from
  `TradingService` at baseline. The exchange work does not add them; that gap
  is pre-existing and recorded in `docs/open_issues.md`.


## Exchange remediation v4 (2026-11-02)

Scope: the findings in `yujtrade_exchange_review_v2_open_issues.md`, executed
under `yujtrade_exchange_remediation_playbook_v4.md`, one commit per phase on
`main`. The review (V2) reported 5 failures on a reconstructed export: two
clock-dependent tracker tests, one Redis uptime test, and two export artifacts
(missing zero-byte `__init__` files and a missing `openspec/` tree). Only the
first two are code defects and are fixed here; the export artifacts are
environment, not code.

Baseline gate (P0): `2164 passed, 13 skipped, 19 deselected` after P1 fixed the
two tracker tests; `ruff` and `mypy domain` clean. Golden hashes recorded and
unchanged at the end.

| Phase | Finding | Commit |
|---|---|---|
| P1 | H-02 clock-dependent tracker fixtures | `eeafee3` |
| P2 | M-03 first Redis failure suppressed | `09d5431` |
| P3 | H-01 read failure escalates to unknown | `7269b23` |
| P4 | M-02/M-04 per-venue reconciliation, bounded blockers | `e6f2f2c` |
| P5 | M-01 duplicate signal must not consume the code | `27d2980` |
| P6 | H-03 strict boolean and list parsing | `eac16fc` |
| P7 | L-01 request timeout applied | `aa6830b` |
| P8 | L-02 unknown rows in the soak report | `c901c2c` |
| P9 | I-02 halt and resume per venue | `6c10cb8` |
| P10 | I-01 operator cancel command | `486b452` |
| P11 | L-04 configuration reference and procedures | `5d16da6` |
| P12 | L-03 documentation and report corrections | this commit |

Still open and blocked on an operator decision or official documentation:
I-03, I-04, I-05, I-06, I-07, L-05, L-06. Recorded in `docs/open_issues.md` and
`docs/operator_pending.md`. Live stays disabled: every live-activation default
is unchanged.
