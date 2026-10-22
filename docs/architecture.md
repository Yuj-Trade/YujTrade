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

## Telegram MarkdownV2 contract

Every Telegram message that is sent with `parse_mode=MarkdownV2` must be
valid MarkdownV2, otherwise the Bot API rejects it with "Can't parse
entities" and the command answers nothing. The rules are:

- A message that is escaped as a whole goes through
  `escape_markdown_v2`, which escapes every reserved character **and** the
  backslash. The text must not be escaped a second time in the source: a
  pre-escaped `\(` becomes `\\(` after the second pass, Telegram reads the
  double backslash as a literal backslash and then finds an unescaped `(`.
- A value that is embedded in a code span (between backticks) goes through
  `escape_code_span`, which escapes only the backtick and the backslash.
  Inside a code span the backslash escapes are not processed, so escaping
  the text level would show a stray backslash in front of every dot.
- A message that mixes formatting markers (bold, code spans) with dynamic
  values escapes the values only, never the whole message.

`tests/unit/app/test_markdown_escaping.py` validates every message the bot
can send against a local MarkdownV2 validator, so a reserved character can
never reach the API unescaped.

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

## Outcome notification flow

```
main.py: OutcomeWatch loop
  -> TradingService.watch_outcomes(policy, now)
       -> SignalTracker.open_signals(now, since)
       -> domain.outcome.observe_signal_barrier   (closed candles only)
       -> SignalTracker.set_outcome_event          (first event wins)
       -> TradingService.reconcile_pending_signals (expiry resolution)
  -> services.outcome_dispatch.dispatch_outcomes(tracker, notifier, policy, now)
       -> SignalTracker.claim_notification / complete_notification / fail_notification
       -> application.outcome_message.render_outcome
       -> OutcomeNotifier.send                     (Telegram in production)
```

The flow is **notify-only**: the observation records an event and never
writes a resolution, never touches the paper ledger and never changes the
outcome of a signal, so the performance report stays reproducible. The
detection uses the closed candles only, therefore the notification delay is
the candle duration plus the watch interval. The delivery is at-least-once
with a claim TTL and a bounded number of attempts.

The policy (`application/outcome_policy.py`) decides the mode, the eligible
kinds, the eligible timeframes, the lower bound and the delivery limits
from the configuration. The channel is the `OutcomeNotifier` protocol
(`application/outcome_ports.py`), so a new channel does not touch the
domain or the loop. `app/tasks.py` is not wired to this flow and must never
run a second stack or a second tracker over the same history.

Decisions: `docs/adr/ADR-0010-signal-outcome-notifications.md`.
