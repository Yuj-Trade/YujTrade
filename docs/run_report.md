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
