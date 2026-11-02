# Exchange remediation v4 - 2026-11-02

Playbook: `yujtrade_exchange_remediation_playbook_v4.md`.
Source review: `yujtrade_exchange_review_v2_open_issues.md`.
Branch: `main`. One commit per phase. No live value written anywhere.

## Baseline (P0)

- Python 3.13.17. `ccxt==4.5.90`, `ruff==0.13.1`, `mypy==1.18.2`.
- Fixtures present (`tests/fixtures`, 5 files).
- Golden hashes at start:

```
d17e604f011a94909796c907321eafb9bd2558e07b50f3d3e5d4e1b4a9c6a512  tests/golden/backtest_baseline.json
a533b2ad45ccb28c52d051a1c982d303c996eb16c150a081c05dfa57c8c09011  tests/golden/backtest_cost_v2_baseline.json
8f7173b71a7cb9bf503a4363542f7319425a3717d0296239d25088d0d75d265a  tests/golden/signals_baseline.json
```

- Baseline pytest (`-m "not slow and not ml"`): `2 failed, 2152 passed, 13
  skipped, 19 deselected`. The two failures are both H-02 (clock-dependent
  tracker fixtures); "now" (2026-11-02) is more than 30 days past the fixture
  date 2026-10-01, so `_prune_expired` deleted the rows.
- `ruff check .` clean; `ruff format --check .` clean; `mypy domain` clean;
  `git diff --check` clean.
- Note: `test_resilient_redis::test_failures_are_reported_once_per_interval`
  passed at baseline on this host because its uptime exceeded the 300 s report
  interval. The V2 export run saw it fail on a low-uptime host; that is M-03.
  The export-artifact failures (missing zero-byte `__init__` files, missing
  `openspec/`) are environment, not code, and do not reproduce in the real tree.

## Phases

### P1 - H-02 clock-dependent tracker fixtures

- Reproduction: base run `assert 0 == 2` in
  `test_summary_counts_resolved_signals_win_rate_and_pending` and the
  notification characterization test.
- Fix: replace the fixed dates in `_details` and `_notification_details` with
  `datetime.now(UTC) - timedelta(...)`, keeping the field order.
- Tests: `51 passed` for the two tracker files.
- Commit: `eeafee3`.

### P2 - M-03 first Redis failure suppressed

- Reproduction: new test `test_the_first_failure_is_reported_on_a_low_uptime_host`
  (monkeypatch `time.monotonic` to `10.0`) failed with `len([]) == 0`.
- Fix: `_last_report: float | None = None`; report when `None` or the interval
  elapsed.
- Tests: `12 passed`.
- Commit: `09d5431`.

### P3 - H-01 read failure escalates to unknown

- Reproduction: `tests/unit/trading/test_reconcile_read_failures.py` failed on
  three cases (`changed == []` where `["cid-1"]` was expected).
- Fix: on a read exception, log a sanitized warning and continue with
  `observed=None` instead of skipping the row.
- Tests: `test_reconcile_read_failures` plus live ledger, identifiers, wiring and
  e2e: `66 passed`. `test_gateway_error_is_skipped` was rewritten to
  `test_gateway_error_before_the_threshold_keeps_the_status` (the old test encoded
  the bug).
- Commit: `7269b23`.

### P4 - M-02 and M-04 per-venue reconciliation and bounded blockers

- Fix: `reconciled_venues: set[str]` replaces the global `reconciled`;
  `reconcile_blockers: dict[str, str]` is rebuilt every pass; the gate refuses
  `reconciliation_pending:<venue>`.
- Tests: new `tests/unit/trading/test_reconcile_per_venue.py`; existing wiring
  tests updated to the new API. `tests/unit/trading`: `382 passed, 3 skipped`.
- Commit: `e6f2f2c`.

### P5 - M-01 duplicate signal must not consume the code

- Reproduction: `test_a_duplicate_signal_does_not_consume_the_code` failed.
- Fix: `append_pending` before `consume_confirmation`; a lost consume race marks
  the row `REJECTED`.
- Tests: new `tests/unit/trading/test_confirmation_order.py`; the old
  `test_code_is_consumed_before_the_row_is_written` was rewritten to the new
  order (`test_the_row_is_written_before_the_code_is_consumed`).
- Commit: `27d2980`.

### P6 - H-03 strict boolean and list parsing

- Reproduction: `parse_bool` did not exist (collection ImportError); the old
  `bool("false")` path returned `True`.
- Fix: `parse_bool(value, key)` with a strict allowlist; `_as_tuple` splits a
  comma-separated string; `exchange_enabled` names must be in the registry;
  `_build_exchange_service` returns `None` on `ExchangeConfigError`.
- Tests: new `tests/unit/trading/test_exchange_config_parsing.py` (36 tests).
  Full suite `2203 passed`.
- Commit: `eac16fc`.

### P7 - L-01 request timeout applied

- Reproduction: `build_gateway(timeout_ms=...)` raised `TypeError`.
- Fix: `build_gateway` takes `timeout_ms`; the service builds one timeout-bound
  factory used by submit and reconcile.
- Tests: new `tests/unit/trading/test_exchange_timeout_wiring.py` (4 tests).
- Commit: `aa6830b`.

### P8 - L-02 unknown rows in the soak report

- Fix: `summarize_shadow_rows` takes `unknown_rows`; `build_report` counts
  `unknown` rows from `get_non_terminal`; `soak_exit_criteria` adds
  `no_unknown_rows`.
- Tests: updated `test_exchange_shadow_report.py`, `10 passed`.
- Commit: `c901c2c`.

### P9 - I-02 halt and resume per venue

- Fix: `halted:<exchange_id>` key; `_evaluate_gate` halts on global OR venue;
  `halt`/`resume` take an optional venue; `halt_state` reports both.
- Telegram: `/exchange_halt [venue]` and `/exchange_resume [venue]` validate the
  venue against the registry and stay admin-only.
- Tests: new `tests/unit/trading/test_exchange_halt_scope.py`; updated
  `tests/unit/app/test_exchange_commands.py`. Full suite `2218 passed`.
- Commit: `6c10cb8`.

### P10 - I-01 operator cancel command

- Fix: `ExchangeGateway.cancel_order`; `CcxtGateway.cancel_order` maps
  `OrderNotFound`/`ExchangeError` and re-raises `NetworkError`; `fetch_snapshot`
  made public; `ExchangeExecutionService.cancel`; `/exchange_cancel <venue>
  <client_order_id>` admin-only.
- Tests: new `tests/unit/trading/test_exchange_cancel.py` (10 tests, including a
  guard that `cancel_order` is only called from cancel and the gateway); updated
  app command tests. Full suite `2231 passed`.
- Commit: `486b452`.

### P11 - L-04 configuration reference and procedures

- `docs/runbook.md`: new 12.9 with every `exchange_*` key (default, meaning,
  safe value) and the strict boolean rule; 12.3 updated for per-venue halt and
  `/exchange_cancel`; 12.4b updated (I-01/I-02 removed, I-03/I-04/L-05/L-06
  added as open decisions).
- `docs/architecture.md`: per-venue halt, cancel path, per-venue reconciliation,
  read-failure escalation, code order.
- Acceptance: all 17 `exchange_*` keys in `config/settings.py` are present in the
  runbook (checked by grep).
- Commit: `5d16da6`.

### P12 - L-03 documentation and report corrections

- `docs/open_issues.md`: G-27 corrected; v4 table added with commits and the
  open items.
- `docs/run_report.md`: v4 section with the commit table.
- `docs/remediation/exchange-remediation-2026-10-29.md`: two false claims
  corrected (unknown rows are not removed from `get_non_terminal`; the code was
  consumed before `append_pending`, fixed in P5).
- `docs/operator_pending.md`: section 11 listing I-03..I-07, L-05, L-06.
- Commit: this commit.
