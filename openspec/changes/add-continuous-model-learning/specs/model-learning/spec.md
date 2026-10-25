## ADDED Requirements

### Requirement: Per-Symbol Background Learning

The system SHALL retrain each model per symbol and timeframe in the background,
outside the signal-generation path.

#### Scenario: Cycle completes before learning starts
- **WHEN** an analysis cycle analyses `BTC/USDT` on `1h`
- **THEN** the cycle returns its signals first and learning for
  `BTC/USDT`/`1h` is scheduled afterwards

#### Scenario: Learning never blocks prediction
- **WHEN** a learning job is running for one symbol
- **THEN** predictions for other symbols are unaffected

### Requirement: Incremental Warm-Start Training

The system SHALL warm-start a retrain from the currently promoted artifact when
one exists.

#### Scenario: Warm start is used
- **WHEN** a promoted artifact exists for the key
- **THEN** the learner trains with `warm_start=True`

#### Scenario: Cold start is allowed
- **WHEN** no artifact exists for the key
- **THEN** the learner trains from a cold initialization and records the
  outcome as a new version

### Requirement: Guarded Promotion

The system SHALL only promote a learned candidate through the existing
promotion gates.

#### Scenario: Degraded candidate is rejected
- **WHEN** a candidate's directional accuracy drops beyond the configured
  tolerance
- **THEN** the candidate is versioned but `current.json` is not moved

#### Scenario: Improved candidate is promoted
- **WHEN** a candidate passes every gate and `model_learning.promote` is true
- **THEN** the registry promotes it and the next prediction loads the new
  version

### Requirement: Bounded and Idempotent Scheduling

The system SHALL bound learning concurrency and avoid duplicate work.

#### Scenario: One job per key
- **WHEN** two cycles request learning for the same symbol/timeframe/model
- **THEN** only one job runs and the second request is ignored

#### Scenario: Minimum interval is respected
- **WHEN** a key was attempted less than `min_interval_minutes` ago
- **THEN** it is skipped until the interval elapses

#### Scenario: Too few new candles
- **WHEN** fewer than `min_new_candles` candles arrived since the last attempt
- **THEN** the key is skipped

### Requirement: Learning Failure Isolation

The system SHALL contain learning failures.

#### Scenario: Training raises
- **WHEN** a learning job raises
- **THEN** the error is logged once for that key and the cycle that follows is
  unaffected
