# Design: add-signal-outcome-notifications

## Layer map

| File | Layer | Responsibility | Allowed dependencies |
|---|---|---|---|
| `domain/outcome.py` | domain | the barrier detection on a closed candle, `OutcomeEvent`, the conversion of a `Resolution` into an event | stdlib |
| `application/outcome_policy.py` | application | `NotificationPolicy`, the configuration validation, the eligibility decision, the failure policy | domain and stdlib |
| `application/outcome_ports.py` | application | `OutcomeNotifier` (protocol) and `NotificationDeliveryError` | domain and stdlib |
| `application/outcome_message.py` | application | the message rendering as plain text | domain and stdlib |
| `strategy/signal_tracker.py` | strategy | the atomic persistence, the notification state, the open and pending queries | stdlib, numpy, common, config, domain |
| `services/trading_service.py` | services | the detection on the candles, the settlement of the expired signals, the metrics | all the layers below |
| `services/outcome_dispatch.py` | services | the delivery loop: claim, send, failure, dispatch in shadow | strategy, application, domain |
| `app/telegram_bot.py` | app | `TelegramOutcomeNotifier`, the implementation of `OutcomeNotifier` | telegram and the existing modules |
| `main.py` | entry | the configuration validation, the `OutcomeWatch` loop, the shared scheduler store | all |
| `config/settings.py` | config | the default keys | - |
| `common/metrics.py` | common | the Prometheus counters with the existing `_PROM` pattern | prometheus_client (optional) |
| `README.md`, `docs/*` | docs | the configuration, the runbook, the architecture, the open issues, the ADR | - |

## Type contracts

### `OutcomeEvent` (domain/outcome.py)

`signal_id: str`, `kind: str` (one of `EVENT_KINDS`), `price: float` (positive
and finite), `at: datetime` (timezone-aware). The invariants are validated in
`__post_init__`.

### `OpenSignal` (strategy/signal_tracker.py)

`signal_id`, `symbol`, `timeframe`, `side` (lower case), `entry`, `stop`,
`target`, `created_at`.

### `PendingNotification` (strategy/signal_tracker.py)

`signal_id`, `event: OutcomeEvent`, `symbol`, `timeframe`, `side`, `entry`,
`created_at`, `attempts: int`.

### `NotificationPolicy` (application/outcome_policy.py)

`mode` (`off`/`shadow`/`live`), `kinds: frozenset[str]`,
`timeframes: frozenset[str]`, `since: datetime | None`, `max_attempts: int`,
`claim_ttl: timedelta`, `watch_interval: timedelta`, `concurrency: int` and
the `enabled` property.

## The notification states

`pending`, `claimed`, `sent`, `shadowed`, `suppressed`, `abandoned`. The
terminal states are `sent`, `shadowed`, `suppressed` and `abandoned`; the set
is exported as `TERMINAL_NOTIFICATION_STATES`.

## The new keys in the signal details

All of them are additive; an older history file is read without a migration.

| Key | Type | Meaning |
|---|---|---|
| `outcome_event` | str | `target`, `stop` or `expired` |
| `outcome_event_at` | str | ISO timestamp of the event |
| `outcome_event_price` | float | the price of the event |
| `notification_state` | str | the notification state |
| `notification_attempts` | int | the number of delivery attempts, `0` by default |
| `notification_claimed_at` | str | ISO timestamp of the claim, only in the `claimed` state |

## The state machine

```
(no event) --set_outcome_event--> pending
pending --claim_notification--> claimed
claimed --complete_notification--> sent | shadowed | suppressed
claimed --fail_notification--> pending | abandoned
pending --fail_notification--> pending | abandoned
```

`set_outcome_event` only accepts the first event of a signal. A claim
expires after `claim_ttl` and becomes claimable again. A failure is
permanent when the delivery error is permanent or when the attempt count
reached `max_attempts`.

## The run loop

```
main.py
  _outcome_watch_loop(policy)
    watch_outcomes(policy, now)      -> detection on the closed candles + settlement
    dispatch_outcomes(tracker, notifier, policy, now)   -> delivery
    scheduler_store.record("outcome_watch", ...)
```

The watch loop is independent of the analysis loop: the expired signals
settle even when `enable_scheduled_analysis` is false. It only runs when
the policy is enabled, and the `outcome_watch` job is recorded in the same
scheduler store as the analysis job.

## The Telegram error mapping

`python-telegram-bot` 22.5 hierarchy:

```
TelegramError
├── RetryAfter
├── Forbidden
└── NetworkError
    ├── BadRequest
    └── TimedOut
```

`BadRequest` is a `NetworkError`, so the handler catches `BadRequest` before
`NetworkError`. The mapping is `RetryAfter`/`TimedOut`/`NetworkError` ->
retryable and `BadRequest`/`Forbidden` -> permanent.

## The performance report must not move

The notification layer never writes a resolution and never touches the
paper ledger. The report is regenerated over a fixed copy of the ledger
before and after every behaviour change and the two outputs are compared
byte for byte.

## The defect fixes

| Id | Root cause | Fix |
|---|---|---|
| D1 | `record` rewrites the details of an existing signal on every cycle | `record_if_absent` |
| D2 | the rotation sorts by age and moves the oldest, whatever the state | the rotation only moves the unprotected entries |
| D3 | `open(...,"w")` truncates the file and a parse error returns `{}` | `write_text_atomic` and a backup of an unreadable file |
| D4 | only the expired signals are listed | the watch loop observes the open signals on the closed candles |
| D5 | the settlement is only called from the analysis cycles | the watch loop settles the expired signals |
| D6 | the pruning only looks at the outcome and the age | the pruning keeps the protected entries |
