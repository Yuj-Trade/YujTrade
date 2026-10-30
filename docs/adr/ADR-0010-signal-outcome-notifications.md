# ADR-0010: Signal outcome notifications

Status: accepted.

## Context

The administrator only learns about the outcome of a signal when the
expired-signal reconciliation runs, and that reconciliation was triggered
by an analysis cycle. A signal that reached its take-profit or its
stop-loss hours before the expiry produced no notification at all, because
`get_pending_expired` only returns the signals whose expiry window has
passed and `enable_scheduled_analysis` is `false` by default.

The tracker could not carry a notification state either. The recording of
an open signal rewrote its creation and its levels on every cycle, the
pruning dropped a resolved signal whose notification had not been delivered
yet, the rotation moved the oldest entries away whatever their state was,
and the history was written non-atomically, so a corrupt file was silently
replaced by an empty one and the next write destroyed the whole history.

The performance report of the previous change must not move: the resolution
of a signal and the ledger are the source of that report.

## Decision

### Notify-only

The notification layer observes and reports. It never writes a resolution,
never touches the paper ledger and never changes the outcome of a signal.
The report over a fixed ledger stays byte-identical, which is checked
before and after every behaviour change.

### The detection uses the closed candles only

`domain/outcome.py:observe_signal_barrier` reports the first stop or target
touch of the window, on the candles whose close is already known. The stop
is still checked before the target inside one candle, and the observation
never reports an expiry, which stays a resolution concern. The inherent
latency is therefore the duration of the candle plus the watch interval.

### The expiry settles independently of the analysis

`TradingService.watch_outcomes` observes the open signals and settles the
expired ones, so the expired signals resolve even when the scheduled
analysis is off. The settlement reuses the existing resolution path, so
the exit reason, the exit time and the ledger write are unchanged.

### Atomic persistence

The history is written through a temporary file and `os.replace`, so a
crash never leaves a half-written file. An unreadable history is moved to
`signal_history.corrupt-<UTC timestamp>.json`, the backup path is logged
and the tracker starts empty: the corrupt content is preserved and never
replaced silently.

### The first detection wins

A signal is recorded only when it is absent, so the first creation, the
first levels and the notification state of an open signal survive the
analysis cycles. An outcome event is only accepted once per signal.

### Protected entries

An entry is protected when it has no outcome yet, or when it has an outcome
event whose notification is not terminal. The pruning and the rotation skip
the protected entries, so a pending notification is never lost. The
rotation only moves the settled entries and warns when the protected
entries do not leave enough room.

### At-least-once delivery with a bounded number of attempts

A notification is claimed, delivered and completed. A permanent delivery
error (a rejected chat, a malformed request) is abandoned immediately, a
retryable one is retried until `outcome_notification_max_attempts` is
reached. The claim TTL bounds the damage of a crashed process: an
unfinished claim becomes claimable again. A duplicated message is preferred
over a lost one.

### Off by default, shadow before live

The mode is `off` by default and a mode other than `off` requires
`outcome_notifications_since`, so a fresh installation cannot replay the
whole history. The `shadow` mode records the events and the state
transitions without sending anything, which makes the volume observable
before it is visible to the administrator.

### The channel is a port

`application/outcome_ports.py` defines the `OutcomeNotifier` protocol and
the delivery error. A new channel (mail, webhook) implements `send` and
nothing else in the domain or in the loop changes.

### The configuration is optional and never stops the bot

An invalid outcome notification configuration is logged and disables the
feature. This is different from the startup contract, where a missing bot
credential ends the run with exit code 2: the outcome notifications are an
optional feature, so their configuration must not take the bot down.

### The Telegram error mapping follows the class hierarchy

In `python-telegram-bot` 22.5 `BadRequest` is a subclass of `NetworkError`,
so `BadRequest` is caught before `NetworkError`; otherwise a rejected
request would be retried instead of being abandoned.

## Consequences

- The administrator receives exactly one message per signal outcome, with
  the state of every delivery visible in `signal_history.json`.
- The observation is cheap: one candle fetch per symbol and timeframe
  group, with a bounded concurrency.
- The performance report is untouched, and the parity between the
  observation and the final resolution is pinned by a randomised test over
  300 series.
- The notification latency is the candle duration plus the watch interval.
  A faster notification would need an intrabar feed, which the data
  provider does not offer.
- `app/tasks.py` is not wired to this flow. It builds a second stack and a
  second tracker over the same `signal_history.json`, so it must never run
  at the same time as the main tracker.

## Limitations

- The `1M` candle duration is a fixed 43200 minutes, so the monthly
  coverage check is approximate.
- The candle fetch is a count, not a time range, so a signal that is
  observed long after its creation may not find a covered window and is
  not observed.
- The delivery channel is Telegram. Another channel needs a new
  `OutcomeNotifier` implementation, nothing else.

## Amendment 2026-10-29 (P9): the faster notification is deferred

The delay documented above (the candle duration plus the watch interval) is
accepted for now. The data provider exposes no intrabar price stream, and a
spot last-price call would not reproduce the stop-first, closed-candle
semantics the resolver depends on, so no faster path is wired.

The seam is reserved instead:

- `application/outcome_ports.py:IntrabarPriceFeed` is a runtime-checkable
  protocol with `async last_price(symbol) -> float | None`.
- `data/intrabar_feed.py:NullIntrabarPriceFeed` returns `None`.
- The outcome watch is not wired to the port; the detection still uses the
  closed candles only, so the behaviour of this ADR is unchanged.

When a venue or provider exposes an intrabar stream, a feed implementation
and a resolver that keeps the stop-first rule can be added behind the same
protocol without touching the domain or the loop. Open issue 15 is marked
deferred (decision G5).
