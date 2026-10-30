# Capability: feature-store

## ADDED Requirements

### Requirement: Feature vector persistence

The feature store SHALL store each model input vector once per `(symbol,
timeframe, candle_time, feature_set_hash)` with the ordered feature list and
the canonical JSON values, and SHALL store at most one label per vector.
Both tables SHALL reject `UPDATE` and `DELETE`. The `feature_set_hash`
SHALL be the SHA-256 of the canonical JSON of the ordered feature list.

#### Scenario: A vector is recorded once

- WHEN the same vector is recorded twice
- THEN the first call returns true, the second returns false and one row
  exists

#### Scenario: A non-finite value is rejected

- GIVEN a vector with a `NaN` or an infinite value
- WHEN it is recorded
- THEN it is rejected and nothing is stored

#### Scenario: The tables reject mutation

- WHEN an `UPDATE` or a `DELETE` is issued against either table
- THEN the database raises an append-only error

### Requirement: Label from the next closed candle

The label of a vector SHALL be the close of the candle at `candle_time +
duration`, and it SHALL be written only when that candle is closed.

#### Scenario: An open label candle is not written

- GIVEN a label candle whose close is not known yet
- WHEN the pending vectors are labelled
- THEN no label is written for that vector

### Requirement: Leakage-free training frame

`training_frame` SHALL return only labelled rows whose label candle is at or
before the requested cutoff, ordered by candle time, and SHALL exclude rows
whose feature set hash differs from the requested one.

#### Scenario: A label after the cutoff is excluded

- GIVEN a vector whose label candle is after `label_before`
- WHEN the training frame is built
- THEN the row is not returned

#### Scenario: A different feature set is excluded

- GIVEN a stored vector whose feature set hash differs
- WHEN the training frame is built
- THEN the row is not returned

### Requirement: Prediction-time capture

The model input vector SHALL be captured at prediction time when the store
is enabled. A capture failure SHALL be logged and SHALL never change the
returned signal. When no ML vector exists, nothing SHALL be recorded.

#### Scenario: The captured vector matches the feature engineer

- GIVEN a fixture series whose window length equals the training window
- WHEN the feature engineer and the store produce the vector at one candle
- THEN the values match within `1e-9`

#### Scenario: The store never changes the signal

- GIVEN the store enabled and disabled on the same fixture
- WHEN the signal is generated
- THEN the returned signal is identical

### Requirement: Store-based training source

The learner SHALL train from the feature store only when the configured
source is the store and the store holds enough labelled rows with the
current feature set. Otherwise it SHALL fall back to the OHLCV frame and log
the reason.

#### Scenario: A low row count falls back

- GIVEN fewer rows than the minimum
- WHEN the learner requests its training frame
- THEN it trains from the OHLCV frame

#### Scenario: A hash mismatch falls back

- GIVEN the stored feature set hash differs from the artifact feature list
- WHEN the learner requests its training frame
- THEN it trains from the OHLCV frame
