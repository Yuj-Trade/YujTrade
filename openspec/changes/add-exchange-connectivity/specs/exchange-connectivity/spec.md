## ADDED Requirements

### Requirement: Venue registry is the single source of truth

The system SHALL expose a frozen registry of 22 exchange specifications. Each
specification SHALL carry `exchange_id`, `display_name`, `ccxt_id`,
`access_scope`, `status`, `spot_supported`, `needs_passphrase`,
`secret_encoding`, `sandbox_expected` and `permission_endpoint`. The registry
SHALL raise `KeyError` for an unknown `exchange_id`, SHALL return unique
`exchange_id` values, and SHALL return unique `env_prefix` values.

#### Scenario: Unknown venue is rejected

- **WHEN** `get_spec` receives an identifier outside the registry
- **THEN** it raises `KeyError` and no network call is attempted

#### Scenario: Registry invariants hold

- **WHEN** the registry is inspected
- **THEN** it holds 22 entries, every `ready` entry has a `ccxt_id`, and
  `iran_only_exchange_ids()` returns `("lbank", "ourbit")`

#### Scenario: Ourbit stays pending

- **WHEN** the Ourbit specification is inspected
- **THEN** its `status` is `pending_docs_verification` and its `ccxt_id` is
  `None`

### Requirement: Access profiles gate venues symmetrically

The system SHALL accept a venue only when its `access_scope` matches the
configured `exchange_access_profile`. A `general` profile SHALL accept only
`general` venues and an `iran` profile SHALL accept only
`iran_users_only` venues. The system SHALL NOT inspect the identity, the
residence or the user of an account.

#### Scenario: Iran profile rejects general venues

- **WHEN** the profile is `iran` and the venue scope is `general`
- **THEN** submission is refused with `scope_mismatch`

#### Scenario: General profile rejects Iran venues

- **WHEN** the profile is `general` and the venue is `lbank` or `ourbit`
- **THEN** submission is refused with `scope_mismatch`

### Requirement: Submission mode is decided by the gate, fail-closed

The system SHALL decide the submission mode from a `GateInput` of booleans in
a fixed order: halted, registry status, spot support, scope, enablement,
sandbox credentials, shadow mode, live credentials, attestation, permissions,
dry-run, live enablement and review acceptance. No live submission SHALL be
returned while any live condition is unmet.

#### Scenario: Halt stops every submission

- **WHEN** the ledger control flag `halted` is `1`
- **THEN** `submission_mode` returns no mode and the reason `halted`

#### Scenario: Default configuration never trades live

- **WHEN** the default configuration is used
- **THEN** no path returns the `live` mode

#### Scenario: Sandbox needs credentials but not a review

- **WHEN** the mode would be sandbox and credentials are absent
- **THEN** the request is refused with `credentials_missing`, and a review id
  is not required for the sandbox mode

#### Scenario: Shadow mode needs no credentials

- **WHEN** shadow mode is enabled
- **THEN** the mode is `shadow` even without credentials

### Requirement: Risk checks reject an unsafe order before any request

The system SHALL check, in order: positive amount and price, symbol allowlist,
venue minimums, per-order notional, per-day notional, price deviation from the
last price, bid/ask spread, and base balance for a sell. The system SHALL
return a stable reason string for every rejection and SHALL NOT call a venue
when a check fails.

#### Scenario: Deviation is rejected

- **WHEN** the limit price deviates from the last price by more than
  `exchange_max_price_deviation_pct`
- **THEN** the request is refused with `price_deviation_exceeded`

#### Scenario: Sell without base balance is rejected

- **WHEN** the side is `sell`, the base balance is known, and it is below the
  requested amount
- **THEN** the request is refused with `insufficient_base_balance`

#### Scenario: Withdrawal is never possible

- **WHEN** the exchange package is scanned for withdrawal, transfer and
  deposit-address calls
- **THEN** no match is found

### Requirement: Exchange secrets decrypt only from encrypted variables

The system SHALL read exchange credentials only from
`ENCRYPTED_<PREFIX>_API_KEY`, `ENCRYPTED_<PREFIX>_API_SECRET` and
`ENCRYPTED_<PREFIX>_API_PASSPHRASE`, with a `_SANDBOX` variant. The system
SHALL NOT fall back to a plaintext variable. A plaintext exchange secret in
`.env` SHALL make the credentials unavailable and SHALL be reported by name
only.

#### Scenario: Plaintext secret disables credentials

- **WHEN** only the plaintext variable is set and no `ENCRYPTED_` value exists
- **THEN** credential loading returns no credentials, the plaintext name is
  reported, and the value never appears in a log, a message or an exception

#### Scenario: Encrypted value round-trips

- **WHEN** an encrypted value is stored for a name
- **THEN** the loader returns the plaintext value, decoding base64 first when
  the specification declares `base64`

### Requirement: Public market data is read-only

The system SHALL fetch the last price, the top of the book and the symbol
precision from a venue without any write call, SHALL reject a symbol whose
market is not spot, and SHALL close the client even when a call fails.

#### Scenario: Non-spot market is rejected

- **WHEN** the requested symbol resolves to a non-spot market
- **THEN** the gateway raises a configuration error and no order is sent

#### Scenario: Probe runs one venue at a time

- **WHEN** the probe script meets a failing venue
- **THEN** the failure is recorded for that venue and the remaining venues are
  still probed

### Requirement: Every order attempt has one durable row

The system SHALL record an order attempt in `runs/live_ledger.db` before the
request leaves the process, with a unique `signal_id` and a unique
`(exchange_id, client_order_id)` pair. The system SHALL reject a duplicate
`signal_id` without sending a second order. A terminal status SHALL never
change.

#### Scenario: Duplicate signal is refused

- **WHEN** a signal with an existing `signal_id` is submitted again
- **THEN** the ledger refuses the insert and no order is sent

#### Scenario: Restart resolves an interrupted order

- **WHEN** the process restarts with a row in `submitted` and reconciliation
  observes the order as filled
- **THEN** the row becomes `filled`, no second row appears and no order is
  re-sent

#### Scenario: Ambiguous status becomes unknown

- **WHEN** the venue returns no order for a row older than
  `exchange_unknown_after_seconds`
- **THEN** the row becomes `unknown` and an administrator notice is produced

### Requirement: Sandbox submission is gated and non-retrying

The system SHALL place a limit order only after the gate and the risk checks
accept it. A network failure SHALL leave the row in `pending_submit` and SHALL
NOT trigger a retry. A non-network failure SHALL mark the row `rejected` with
a sanitized reason.

#### Scenario: Accepted sandbox order is recorded

- **WHEN** the gate returns sandbox and the venue returns an order id
- **THEN** the row becomes `submitted` with the venue order id

#### Scenario: Timeout leaves the row pending

- **WHEN** the venue raises a timeout during submission
- **THEN** the row stays `pending_submit` and no retry occurs

### Requirement: Shadow mode places no order

The system SHALL record a signal in shadow mode as a `shadow` row and SHALL NOT
call the venue order method. A shadow report SHALL summarize the shadow rows
without any secret value.

#### Scenario: Shadow never orders

- **WHEN** a signal is submitted in shadow mode
- **THEN** the venue order method is called zero times and the row status is
  `shadow`

### Requirement: Live activation needs a review and a one-time code

The system SHALL require `execution_dry_run` false, `exchange_sandbox` false,
`exchange_live_enabled` true, an accepted review id, a key attestation and
verified permissions before the live mode is returned. A live execution
request SHALL additionally require a one-time confirmation code that expires
after 60 seconds and cannot be reused.

#### Scenario: Missing review blocks live

- **WHEN** the review id does not map to an ADR file whose status is
  `accepted`
- **THEN** the gate refuses with `review_not_accepted`

#### Scenario: Code expires

- **WHEN** the confirmation code is presented after its 60 second window
- **THEN** the live submission is refused

#### Scenario: Sandbox needs no code

- **WHEN** the mode is sandbox or shadow
- **THEN** no confirmation code is required

### Requirement: Administrator commands expose no secret

The system SHALL provide administrator-only commands for the venue list, an
order status, an execution request, a halt and a resume. A non-administrator
SHALL observe no state change. No command SHALL print a credential or enable
the live mode.

#### Scenario: Non-admin sees no change

- **WHEN** a non-administrator invokes an exchange command
- **THEN** no ledger write, no order and no mode change occurs
