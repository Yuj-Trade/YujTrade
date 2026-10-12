# Architecture (behavioral contracts moved out of code comments)

Code files carry no rationale comments by rule; this document owns the
contracts that used to live in them.

## Signal error contract (rule 30)

`SignalGenerator.generate_signal` returns `None` for a healthy
"no signal" decision (HOLD between thresholds, risk/reward below minimum,
multi-timeframe conflict, application gate rejection). It raises only for
analysis failure (bad data, data/compute errors), which must reach the
caller and never be converted to `None`. `TradingService` separates the two
via result partitioning: signals flow on, exceptions are counted in
`last_errors` and logged.

## Pipeline data flow (rule 6)

Market Data -> Market Regime -> Existing Weight Adjustment -> Scoring.
Regime detection consumes raw market data; indicator weight adjustment
consumes the regime; scoring consumes adjusted weights. No stage is skipped
or reordered.

## Historical purity (rule 14)

Backtest and holdout paths run with `include_external=False` and
`include_ml=False` so no live-only data leaks into historical evaluation.
`--with-ml` on the holdout is refused unless every current artifact's
`data_end` predates the holdout window.

## Signal ownership (rule 23)

A signal is not analyzable until data passes quality validation; invalid
data raises `InsufficientDataError` (analysis failure), never `None`.

## Composition root (rule 18)

`main.py` holds the single composition root: one place builds the config,
resources, data provider and trading service. No parallel wiring graphs.

## Layering

`domain` <- `application` <- everything else. `domain` imports only the
standard library; `application` imports only `domain` and the standard
library. Enforced by `tests/unit/test_architecture.py`.

## Gate ownership

`application/gate_config.py:build_gate_config` is the single source of gate
construction for both the generator and the service. Confidence scaling
lives in `domain/gates.py:normalize_confidence` (0-100 scale; non-finite
maps to 0). Level geometry validation lives in
`domain/levels.py:validate_levels` and runs before quality gates in
`application/decide.py`.
