# Proposal: add-learning-alerts

Approval: approved by YT-IMPL-SPEC Revision 2.0 (2026-10-29), decisions G1
and G4.

## Why

Continuous learning sends no notifications at all. A promotion, a rejection,
a failure and a feature-drift notice are only visible in the log, and
`model_learning.enabled` is `false` with no auditable review step before an
operator turns it on.

## What Changes

- `application/learning_alerts.py` holds a `LearningEvent`, a
  `LearningAlertSink` protocol, a plain-text renderer and an `AlertBuffer`
  that flushes in order when a sender is attached.
- `ModelLearner` emits `promoted`, `rejected`, `failed` and
  `promotion_failed`, and computes drift on every eligible job with a
  per-key cooldown, whether or not the drift gate is on.
- `TradingService` owns one `AlertBuffer`; `MainApp.run` attaches the
  Telegram notifier once at startup.
- `scripts/review_learning_artifacts.py` is a read-only gate; continuous
  learning is enabled in the local `config.json` only when the gate exits
  `0`. The committed default stays `false`.

## Impact

- Affected specs: `model-learning`
- Affected code: `application/learning_alerts.py` (new),
  `modeling/learner.py`, `services/trading_service.py`, `main.py`,
  `config/settings.py`, `scripts/review_learning_artifacts.py` (new)
- `config.json` is gitignored and never committed.
