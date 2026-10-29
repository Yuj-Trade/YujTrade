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

| Phase | Status |
|---|---|
| 0. Governance | done |
| 1. Baseline and adapter fixes | done |
| 2. Domain, ports, policy, registry | done |
| 3. Encrypted secrets | done |
| 4. Read-only market data | done (network probe `blocked_by_operator`) |
| 5. Authenticated reads and permission check | done (LBank rule `blocked_by_operator`) |
| 6. Live ledger and reconciliation | done |
| 7. Sandbox submission | done (real sandbox test `blocked_by_operator`) |
| 8. Telegram controls | done |
| 9. Shadow mode | done (14-day soak `blocked_by_operator`) |
| 10. Live activation mechanism | done (activation `blocked_by_operator`) |
| 11. Further general venues | done as code + documented procedure (probe `blocked_by_operator`) |
| 12. Iran profile | done for LBank; Ourbit `blocked_by_operator` |
| 13. Operations | done |

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

