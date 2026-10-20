# Proposal: add-signal-outcome-notifications

## Why

The administrator only learns about a signal outcome when the expired-signal
reconciliation runs, and that reconciliation is triggered by an analysis
cycle. A signal that reached its take-profit or stop-loss hours before the
expiry therefore produces no notification at all: `get_pending_expired`
returns only the signals whose expiry window has passed, and
`reconcile_pending_signals` is only called from the analysis cycles, which
are disabled by default (`enable_scheduled_analysis=false`).

The tracker also cannot carry a notification state. `_record_locked` rewrites
an open signal on every analysis cycle (the signal id is derived from the
candle index, so it is stable, but the details are rewritten), `_prune_expired`
drops resolved entries after the TTL even when their notification has not
been delivered yet, `_rotate_if_needed` moves the oldest entries away
regardless of their state, and the history is written non-atomically: a
corrupt file is silently replaced by `{}` and the next write then destroys
the whole history.

## What Changes

1. **Notify-only outcome events.** `domain/outcome.py` gains
   `observe_signal_barrier`, which detects the first stop or target touch on
   closed candles, and `OutcomeEvent`, the value object that carries the
   event. Expiry stays a resolution concern, not an event.
2. **Notification state in the tracker.** `strategy/signal_tracker.py` gains
   the notification state API (`set_outcome_event`, `open_signals`,
   `due_notifications`, `claim_notification`, `complete_notification`,
   `fail_notification`) and the additive detail keys `outcome_event`,
   `outcome_event_at`, `outcome_event_price`, `notification_state`,
   `notification_attempts` and `notification_claimed_at`.
3. **Atomic, non-destructive persistence.** The history is written through a
   temporary file and `os.replace`; an unreadable history is moved aside to
   `signal_history.corrupt-<UTC timestamp>.json` and never overwritten
   silently.
4. **Protected entries.** A new signal is only recorded when it is absent, a
   rotation only moves settled entries, and the pruning keeps an entry whose
   notification is not terminal.
5. **A policy layer.** `application/outcome_policy.py` reads the
   configuration and decides the mode, the eligible event kinds, the
   eligible timeframes, the lower bound and the delivery limits.
   `application/outcome_ports.py` defines the `OutcomeNotifier` protocol and
   the delivery error, `application/outcome_message.py` renders the message.
6. **An independent watch loop.** `TradingService.watch_outcomes` observes
   the open signals on closed candles and settles the expired ones, and
   `services/outcome_dispatch.py` delivers the due notifications with an
   at-least-once claim. `main.py` runs the loop and records the
   `outcome_watch` job in the shared scheduler store.
7. **A Telegram channel.** `app/telegram_bot.py` gains
   `TelegramOutcomeNotifier`, the implementation of the delivery port.
8. **Configuration, metrics and documentation.** The eight new
   configuration keys live in `ConfigManager.DEFAULT_CONFIG`, two new
   Prometheus counters live in `common/metrics.py`, and `README.md`,
   `docs/architecture.md`, `docs/runbook.md`, `docs/open_issues.md` and
   `docs/adr/ADR-0010-signal-outcome-notifications.md` describe the feature.

## Out of scope (forbidden)

- Changing when a resolution is written to the ledger.
- Changing the formulas of the performance report.
- Changing the meaning of `resolved_at` and `exit_at`.
- With a fixed ledger, the output of `scripts/generate_performance_report.py`
  must stay byte-identical.
- `app/tasks.py` is not touched: it must not be wired to `main.py` or to
  `app/telegram_bot.py`, and it must not run a second stack or a second
  `SignalTracker` over the same `signal_history.json`.
- No new stack: `create_trading_stack()` remains the only composition root.
- No live trading, no change to `execution_dry_run`, no change to
  `LONG_TERM_CONFIG`, no change to the signal generation and the indicators.
- No change to `tests/golden/*.json` and no change to the recording scripts.

## Decisions

- **Notify-only.** The notification layer observes and reports; it never
  writes a resolution, never touches the paper ledger and never changes the
  outcome of a signal. The report therefore stays reproducible.
- **Detection on closed candles only.** A candle whose close is not yet
  known is not a barrier event. The inherent notification latency is one
  candle duration plus the watch interval.
- **At-least-once delivery with a bounded number of attempts.** A
  notification is claimed, delivered and completed. A delivery error is
  retried until `outcome_notification_max_attempts` is reached. A permanent
  error (a rejected chat, a malformed request) is abandoned immediately.
  The claim TTL bounds the damage of a crashed process: an unfinished claim
  becomes claimable again.
- **Default off.** `outcome_notifications_mode` defaults to `off` and a
  mode other than `off` requires `outcome_notifications_since`, so a fresh
  installation cannot spam the administrator with the whole history.
- **Shadow before live.** `shadow` records the events and the state
  transitions without sending anything, which makes the rollout observable
  before it is visible to the administrator.
- **Atomic persistence.** The history is written through a temporary file
  and `os.replace`, so a crash never leaves a half-written file, and an
  unreadable history is backed up instead of being replaced by an empty one.
- **Additive state.** The new detail keys are additive, so an older history
  file is read without a migration.
- **Delivery is a port.** `OutcomeNotifier.send` is the only channel
  contract, so a new channel (mail, webhook) does not touch the domain or
  the dispatch loop.
- **The Telegram error mapping follows the class hierarchy.** In
  `python-telegram-bot` 22.5 `BadRequest` is a subclass of `NetworkError`,
  so `BadRequest` is caught before `NetworkError`; otherwise a rejected
  request would be retried instead of being abandoned.

## Configuration keys

| Key | Type | Default | Rule |
|---|---|---|---|
| `outcome_notifications_mode` | str | `"off"` | one of `off`, `shadow`, `live` |
| `outcome_notifications_since` | str | `""` | required and ISO with timezone for a mode other than `off` |
| `outcome_notification_kinds` | list[str] | `["target", "stop", "expired"]` | non-empty, subset of the event kinds |
| `outcome_notification_timeframes` | list[str] | `[]` | empty means every allowed timeframe |
| `outcome_watch_interval_minutes` | number | `15` | greater than zero |
| `outcome_notification_max_attempts` | int | `3` | at least one |
| `outcome_claim_ttl_seconds` | number | `300` | greater than zero |
| `outcome_watch_concurrency` | int | `4` | at least one |

## Known defects this change fixes

| Id | Defect | Fixed in |
|---|---|---|
| D1 | re-recording an open signal rewrites its creation and its levels | stage 3 |
| D2 | the rotation removes the oldest entries regardless of their state | stage 3 |
| D3 | the history is written non-atomically and a corrupt file is silently overwritten | stage 2 |
| D4 | a target or a stop before the expiry is never observed | stage 7 |
| D5 | the expired signals only settle from the analysis cycle | stages 7 and 8 |
| D6 | the pruning removes a resolved entry whose notification is still open | stage 3 |

## Risks

- **A notification storm.** The `since` bound and the default-off mode
  limit the exposure. The shadow mode makes the volume observable before it
  is sent.
- **A duplicate notification.** At-least-once delivery can repeat a message
  when the process dies between the send and the completion. The claim TTL
  bounds the window; a duplicated message is preferred over a lost one.
- **A rotated pending notification.** The rotation only moves the settled
  entries, so a pending notification is never rotated away.
- **Load.** The watch loop fetches the candles once per symbol and
  timeframe group, and the concurrency is bounded.
- **The report must not move.** The performance report is compared before
  and after every behaviour change against a fixed copy of the ledger.

## Rollback

Set `outcome_notifications_mode` back to `off` and restart the bot. The
state is additive, so no migration is needed. A pending notification stays
pending and is processed again at the next activation, unless a new `since`
bound excludes it.
