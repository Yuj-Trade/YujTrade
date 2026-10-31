# Exchange connectivity remediation, 2026-10-29

Input: `yujtrade_exchange_connectivity_review.md`, findings G-01 to G-26, and the
remediation playbook version 3.

All work on `main`. No branch, worktree, tag or stash created. Every commit was
made after the gate was green. Nothing in this run enables live trading: no live
value is written to a tracked file or to a default.

## R0: preparation and baseline

Starting point: `main` at `6018b29`, working tree clean. Python 3.13.15.
Pinned tools: `ccxt==4.5.90`, `ruff==0.13.1`, `mypy==1.18.2`.

The review was taken against a bundle built from an earlier `main`. Since then
32 commits landed on `main` that touch `services/trading_service.py` and
`app/telegram_bot.py`. Each finding was re-checked against the current tree
before remediation; G-11 was already fixed upstream and is recorded as such.

| Gate | Result |
|---|---|
| `python -m pytest -m "not slow and not ml" -q` | 2043 passed, 13 skipped, 19 deselected |
| `ruff check .` | clean |
| `ruff format --check .` | clean (294 files) |
| `mypy domain` | clean (10 source files) |
| `git diff --check` | clean |

Golden hashes at baseline:

```text
d17e604f011a94909796c907321eafb9bd2558e07b50f3d3e5d4e1b4a9c6a512  tests/golden/backtest_baseline.json
a533b2ad45ccb28c52d051a1c982d303c996eb16c150a081c05dfa57c8c09011  tests/golden/backtest_cost_v2_baseline.json
8f7173b71a7cb9bf503a4363542f7319425a3717d0296239d25088d0d75d265a  tests/golden/signals_baseline.json
```

A third golden file (`backtest_cost_v2_baseline.json`) exists that the earlier
run did not record. It is part of the current baseline and must not change
either.

Re-check against the current tree:

| Finding | State before remediation |
|---|---|
| G-01 | open — `LiveLedger` built without `initialize()`, no lazy schema |
| G-02 | open — `reconcile_once` has no production caller |
| G-03 | open — `issue_confirmation` unused, code never reaches `submit_signal` |
| G-04 | open — `portfolio.equity(entry, stop)` called with two arguments |
| G-05 | open — 32-character id, `userref = signal_id[:8]` for Kraken |
| G-06 | open — shadow rows carry no reference price, refusals not stored |
| G-07 | open — code consumed before the risk checks |
| G-08 | open — permission check on every call, no cache, runs in sandbox |
| G-09 | open — order lookup only by `clientOrderId` |
| G-10 | closed upstream — `domain/__init__.py` exists, `mypy domain` clean |
| G-11 | closed upstream — `execute_signal` and `portfolio_snapshot` exist |
| G-12 | open — kucoin `sandbox_expected=True` |
| G-13 | open — operator item, unchanged |
| G-14 | open — ADR-0011/0012 accepted without written confirmation |
| G-15 | open — proposal status is `approved` |
| G-16 | open — run report overstates phases 6, 7, 8, 10 |
| G-17 | open — ADR path depends on the working directory |
| G-18 | open — sizing error swallowed at debug level |
| G-19 | open — `TypeError` and `AttributeError` both mapped to sandbox error |
| G-20 | open — dead helpers |
| G-21 | open — reconcile interval configured, never used |
| G-22 | open — env seed script outside the playbook |
| G-23 | open — connection per ledger call, accepted limitation |
| G-24 | open — halt does not cancel open orders, documentation item |
| G-25 | open — LBank never live, by design |
| G-26 | open — Ourbit blocked, by design |

## R1: governance (G-14, G-15)

`ADR-0011` and `ADR-0012` were recorded as accepted on the strength of a
one-shot approval the operator never wrote. Both are now `proposed`, with an
explicit `Approval: pending.` line. The terms-of-use statement in ADR-0012 is
recorded as pending. The OpenSpec proposal is `pending approval`.

The live gate is unchanged: `review_is_accepted` still reads the `Status:` line,
so both venues now fail with `review_not_accepted`. This is the intended
fail-closed result.

- Commit: `ffb1351` docs(governance): return ADR-0011 and ADR-0012 to proposed
- Tests: `tests/unit/docs/test_exchange_governance.py` (8 tests), including a
  live-gate test that proves the proposed status keeps live closed.
- Two older confirmation tests assumed the accepted status; they now pass an
  explicit `review_ok=True` override so the confirmation logic stays covered
  independently of the governance state.

## R2: gate and domain packaging (G-10)

Closed upstream before this run: `domain/__init__.py` exists (added in
`322007a`) and `mypy domain` is clean with the pinned `mypy==1.18.2`.

- Added a regression guard in `tests/unit/test_architecture.py` so `domain` and
  `application` cannot lose their package markers again.
- Gate: `mypy domain` clean, architecture and purity tests green, golden
  unchanged.
- No commit of its own; the guard rode with the R1 commit.

## R3: ledger schema on first use (G-01)

Reproduced first: `tests/unit/trading/test_live_ledger_lazy_schema.py` on a fresh
`LiveLedger` without `initialize()` gave 7 failures with
``sqlite3.OperationalError: no such table: live_control`` and
``live_orders``. ``/exchange_halt`` therefore failed, so the emergency stop did
not work.

Fix: ``_schema_ready`` flag plus ``_ensure_schema``; ``_connect`` now creates the
schema on the first connection. ``initialize()`` stays public and idempotent.

- Commit: `5174c26` fix(exchange): create the live ledger schema on first use
- Tests: the same file now passes (8 tests), including "halt records the flag on
  a fresh ledger" and "halt blocks submission on a fresh ledger".
- Gate: 2060 passed; architecture test green (still no ``sqlite3.connect`` in
  runtime); golden unchanged.

## R4: order identifiers and lookup (G-05, G-09)

Reproduced: the Gate limit was confirmed in the pinned source
(`ccxt/gate.py`: "no longer than 28 bytes without t- prefix"). The old code sent
a 32-character id to every venue and a symbol fragment as Kraken `userref`.

Fix:

- `ExchangeSpec` gains `client_id_supported: bool = False` and
  `client_id_max_len: int = 32`; Gate is the only venue with 28.
- `make_client_order_id(exchange_id, signal_id, max_len)` truncates the digest.
- `_order_params` sends `clientOrderId` only when the venue is verified. Kraken,
  LBank, Bitvavo and Gate send nothing until their documentation is confirmed.
- `fetch_order_by_exchange_id` added to the gateway and to the
  `ExchangeGateway` protocol; `_fetch_snapshot` prefers the stored venue id and
  falls back to the client id only for a verified venue.

- Commit: `4c0f3f0` fix(exchange): send client order ids only where the venue
  limit is verified and look orders up by venue id
- Tests: `tests/unit/trading/test_order_identifiers.py` (14 tests) covering the
  Gate cap, no identifier for unverified venues, lookup order, and the unknown
  transition when neither lookup is possible.
- No venue is marked `client_id_supported` yet; that stays an operator step.
