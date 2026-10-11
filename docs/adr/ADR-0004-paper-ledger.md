# ADR-0004: Paper ledger and idempotency

Status: accepted.

## Context

Telegram delivery retries and overlapping scheduled runs can submit the same
signal twice. A paper ledger that records both would double-count exposure
and corrupt equity history; one that silently drops the second without a
trace hides operational problems.

## Decision

Paper orders live in SQLite (`trading/ledger.py`, default
`runs/paper_ledger.db`) with a `UNIQUE` constraint on `signal_id`.
`append_order` returns `None` on a duplicate instead of raising; the
rejection is therefore explicit at the call site and countable in tests.
Equity snapshots are computed from caller-supplied mark prices, never from
entry prices: a position without a fresh mark is flagged `stale` in the
database, excluded from equity, and logged with a warning.

## Consequences

- Retried or overlapping submissions are idempotent by construction.
- Stale marks degrade visibly (flag + log + excluded equity) instead of
  silently reusing entry prices.
- `tests/unit/trading/test_ledger_parity.py` covers rejection, recording,
  mark-price valuation, and the stale path.
- Cost: SQLite is single-writer; concurrent writers serialize on the
  database lock. Sufficient for one bot process.
