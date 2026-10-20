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

## Paper performance flow

```
reconcile_pending_signals
  -> domain.outcome.resolve_signal_outcome   (pure: window, coverage, exit reason)
  -> trading.ledger.PaperLedger.record_resolution   (append-only signal_resolutions)
  -> strategy.signal_tracker.resolve / update_resolution_details
```

The resolution is a pure domain decision. The service only fetches the
candles, asks the domain and hands the outcome to the ledger; it never
computes an exit price itself and never uses the current market price as
an exit. The ledger row is written before the tracker is synchronised, so
a failed write leaves the signal pending and the next cycle retries it.

```
PaperLedger.signal_resolutions
  -> services.trading_service.build_performance_report(as_of)
  -> application.performance_report.build_performance_report(records, config, as_of)
       -> domain.performance (net R, equity curve, daily series, MDD, Sharpe, Sortino)
```

The report builder is the only place that composes the metrics, the
service only loads the data and the display layers (the Telegram command
and `scripts/generate_performance_report.py`) only render the result. The
report carries a `data_hash` over the included records and a `config_hash`
over the effective parameters, so the same ledger and configuration always
produce the same report.

Definitions, decisions and limitations: `docs/adr/ADR-0009-performance-metrics.md`.
Worked example: `docs/performance-worked-example.md`.
