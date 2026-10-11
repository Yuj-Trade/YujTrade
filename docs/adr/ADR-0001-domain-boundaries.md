# ADR-0001: Domain boundaries

Status: accepted.

## Context

Signal math (outcome resolution, position sizing, level calculation, quality
gates) must behave identically whether it runs in the live pipeline, the
paper trader, or the backtest simulator. Duplicated logic in each caller
drifts; a shared impure helper invites hidden I/O and lookahead bias.

## Decision

All decision math lives in `domain/` as pure functions over plain data
(`outcome.py`, `sizing.py`, `levels.py`, `gates.py`, `types.py`,
`signal_id.py`). The package depends on the standard library only and is
type-checked strictly (`mypy domain`). Adapters translate
provider-specific objects (DataFrames, ORM rows, exchange payloads) into
domain inputs before calling in. `application/` (`decide.py`,
`snapshot.py`) orchestrates `domain` calls; infrastructure
(`backtesting/`, `modeling/`, `trading/`, `services/`, `app/`) never
implements decision math of its own.

## Consequences

- Parity between live, paper, and backtest is structural, not conventional;
  `tests/unit/trading/test_ledger_parity.py` pins it.
- The import direction is enforced by `tests/unit/test_architecture.py`
  (AST contract, no new dependencies): `domain` takes stdlib only,
  `application` takes `domain` plus stdlib.
- Cost: callers must map their rich objects to domain inputs at the
  boundary; new decision logic cannot shortcut through infrastructure.
