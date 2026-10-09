# ADR-0004: Paper ledger and idempotency

Paper orders are recorded in SQLite with a unique `signal_id`. Duplicate
signals are rejected without creating a second order. Equity snapshots use
mark prices supplied by the caller.
