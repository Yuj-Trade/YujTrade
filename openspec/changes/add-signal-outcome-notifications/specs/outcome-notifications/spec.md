# Capability: outcome-notifications

## ADDED Requirements

### Requirement: Exactly one outcome notification per signal

The system SHALL send at most one outcome notification per signal: the first
take-profit touch, the first stop-loss touch or the expiry. سیستم باید برای
هر سیگنال حداکثر یک اعلان نتیجه بفرستد: اولین لمس TP، اولین لمس SL، یا
انقضا. A signal without an event must not be notified and a signal whose
event is already recorded must not be notified a second time.

#### Scenario: The first touch is the only one that is notified

- GIVEN an open buy signal whose target is touched on a closed candle
- WHEN the watch loop observes the signal
- THEN exactly one outcome event is recorded for the signal
- AND the notification state becomes `pending`
- AND a later touch of the other barrier does not create a second event

#### Scenario: A signal without an event is not notified

- GIVEN a signal without an outcome event
- WHEN the dispatch loop runs
- THEN no message is sent for that signal

#### Scenario: An event that is already terminal is not sent again

- GIVEN a signal whose notification state is `sent`
- WHEN the dispatch loop runs again
- THEN no message is sent for that signal

### Requirement: The detection only uses closed candles

The detection SHALL only use closed candles. تشخیص لمس باید فقط روی
کندل‌های بسته انجام شود. A candle whose closing time is after the
observation instant must not produce an event.

#### Scenario: The last open candle is ignored

- GIVEN an open buy signal and a candle that would touch the target but
  whose close is not yet known
- WHEN the watch loop observes the signal
- THEN no outcome event is recorded for that candle

#### Scenario: The stop wins over the target inside one candle

- GIVEN a closed candle whose range contains both the stop and the target
- WHEN the watch loop observes the signal
- THEN the recorded event is the stop

### Requirement: The notification does not change the resolution

The notification MUST NOT change the ledger, the final outcome or the
performance report. اعلان نباید هیچ تغییری در ledger، outcome نهایی یا
گزارش عملکرد ایجاد کند. The observation of an event must not write a
resolution, must not change the outcome of a signal and must not change the
performance report.

#### Scenario: Observing a target leaves the outcome untouched

- GIVEN an open signal whose target is touched on a closed candle
- WHEN the watch loop observes the signal
- THEN the outcome of the signal stays unset
- AND the paper ledger is not written
- AND the performance report over a fixed ledger stays byte-identical

#### Scenario: The expiry still resolves the signal

- GIVEN a signal whose expiry window has passed
- WHEN the watch loop settles the expired signals
- THEN the signal is resolved exactly as before
- AND the resolution keeps its own exit reason and its own exit time

### Requirement: The delivery is at-least-once with a bounded number of attempts

The delivery SHALL be at-least-once with a bounded number of attempts. تحویل
باید at-least-once با حد تلاش مشخص باشد. A permanent error must abandon the
notification immediately. A retryable error must leave the notification
pending until the attempt limit is reached.

#### Scenario: A successful delivery is completed

- GIVEN a pending notification and a notifier that accepts the message
- WHEN the dispatch loop runs
- THEN the message is sent once and the state becomes `sent`

#### Scenario: A permanent error is abandoned immediately

- GIVEN a pending notification and a notifier that raises a permanent
  delivery error
- WHEN the dispatch loop runs
- THEN the state becomes `abandoned` and the message is not retried in the
  same run

#### Scenario: A retryable error is retried until the limit

- GIVEN a pending notification and a notifier that always raises a
  retryable delivery error
- WHEN the dispatch loop runs repeatedly
- THEN the state stays `pending` until the attempt limit
- AND the state becomes `abandoned` at the limit

#### Scenario: An unfinished claim becomes claimable again

- GIVEN a notification that is claimed and whose claim is older than the
  claim TTL
- WHEN the dispatch loop runs
- THEN the notification is claimed again

### Requirement: The feature is off by default

The feature SHALL be off by default. قابلیت باید به‌صورت پیش‌فرض خاموش
باشد. A mode other than `off` without a valid `outcome_notifications_since`
must be rejected.

#### Scenario: The default configuration is off

- GIVEN the committed default configuration
- WHEN the policy is built
- THEN the mode is `off` and the policy is not enabled

#### Scenario: A live mode without a since bound is rejected

- GIVEN a configuration with the mode `live` and an empty
  `outcome_notifications_since`
- WHEN the policy is built
- THEN the policy is rejected with an explicit error

#### Scenario: An invalid configuration does not stop the bot

- GIVEN an invalid outcome notification configuration
- WHEN the application starts
- THEN the error is logged, the feature is disabled and the application
  keeps running

### Requirement: The event kinds and the timeframes come from the configuration

The event kinds and the timeframes SHALL be read from the configuration. نوع
رویدادها و تایم‌فریم‌های اعلان باید از پیکربندی خوانده شوند. The
notification interval, the concurrency, the attempt limit and the claim TTL
must be configurable as well, and no default may be duplicated in a service
or in a script.

#### Scenario: The configured kinds are the only notified kinds

- GIVEN a policy with the kinds `target` and `stop`
- WHEN an expired signal is dispatched
- THEN the expired event is suppressed and the state becomes `suppressed`

#### Scenario: The configured timeframes limit the observation

- GIVEN a policy that only covers the `1d` timeframe
- WHEN an open `1h` signal is observed
- THEN that signal is not observed

#### Scenario: The defaults live in the configuration

- GIVEN the committed default configuration
- WHEN the policy is built from it
- THEN every outcome notification key has its documented default

### Requirement: The history is written atomically and a corrupt file is backed up

The history SHALL be written atomically and a corrupt file MUST NOT be
silently rewritten. ذخیره‌ی تاریخچه باید اتمیک باشد و فایل خراب نباید بی‌صدا
بازنویسی شود. A write must never leave a half-written file, and an
unreadable history must be moved aside instead of being replaced by an empty
one.

#### Scenario: The write is atomic

- GIVEN a tracker with a history
- WHEN the history is saved
- THEN the file is replaced atomically and the previous content is never
  partially overwritten

#### Scenario: A failed write leaves the previous file intact

- GIVEN a tracker with a saved history
- WHEN the atomic replace fails
- THEN the previous file is unchanged and the error is raised

#### Scenario: A corrupt history is backed up

- GIVEN a history file with an invalid JSON content
- WHEN the tracker loads it
- THEN the file is moved to a `signal_history.corrupt-<UTC timestamp>.json`
  backup, an error is logged and the tracker starts empty
- AND the original file is not overwritten in place
