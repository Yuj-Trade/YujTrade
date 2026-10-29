# Capability: model-learning

## ADDED Requirements

### Requirement: Learning outcome alerts

The learner SHALL emit an alert for a promotion, a rejection, a training
failure and a promotion failure. An alert SHALL be rendered as plain text
and delivered through the configured sink. A sink failure SHALL be logged
and SHALL never stop the learning job.

#### Scenario: A promotion is announced

- GIVEN a candidate that passes the promotion guard
- WHEN the learner promotes it
- THEN a `promoted` event is emitted for the key

#### Scenario: A rejection is announced

- GIVEN a candidate the promotion guard rejects
- WHEN the learner finishes the job
- THEN a `rejected` event is emitted with the reasons

#### Scenario: A sink failure does not stop learning

- GIVEN a sink whose send raises
- WHEN the learner emits an event
- THEN the error is logged and the job completes

#### Scenario: The buffer flushes on attach

- GIVEN events recorded before a sender is attached
- WHEN the sender is attached
- THEN the buffered texts are sent in order

### Requirement: Drift detection is monitored

The learner SHALL compute feature drift on every job that passes the
minimum-new-candles check, whether or not the drift gate is on, and SHALL
emit at most one `drift_detected` event per key per cooldown window.

#### Scenario: Drift is announced with the gate off

- GIVEN `drift_gate` is false and the data drifted
- WHEN the learner runs a job
- THEN a `drift_detected` event is emitted

#### Scenario: The cooldown suppresses a repeat

- GIVEN a drift event was emitted for the key inside the cooldown
- WHEN the learner runs another job for the key
- THEN no second event is emitted

### Requirement: Read-only learning review gate

`scripts/review_learning_artifacts.py` SHALL verify every current artifact,
compare it with the previous version when one exists, write the review
document, and SHALL never promote or modify an artifact. It SHALL exit `0`
only when every current artifact verifies and at least one exists.

#### Scenario: A verified tree passes

- GIVEN a temporary artifact tree whose current versions verify
- WHEN the script runs
- THEN it exits `0` and writes the review document

#### Scenario: A tampered file fails

- GIVEN a current artifact whose file hash no longer matches
- WHEN the script runs
- THEN it exits `1`

#### Scenario: An empty tree fails

- GIVEN no current artifact
- WHEN the script runs
- THEN it exits `1`

### Requirement: Local enablement only behind the gate

Continuous learning SHALL be enabled only in the untracked local
configuration, only when the review gate exits `0`. The committed default
SHALL stay `false`.

#### Scenario: The committed default stays off

- WHEN the committed `ConfigManager.DEFAULT_CONFIG` is read
- THEN `model_learning.enabled` is `false`

#### Scenario: The gate blocks enablement

- GIVEN the review gate exits `1`
- WHEN the enablement step runs
- THEN `config.json` is left unchanged and the blocker is recorded
