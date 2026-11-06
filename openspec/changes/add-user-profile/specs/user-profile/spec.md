# User-profile Specification

## ADDED Requirements

### Requirement: Profile schema defaults preserve current behavior

The system SHALL declare every personalizable key in a profile schema whose
defaults equal the current `ConfigManager.DEFAULT_CONFIG` values; when no
override is stored, the running values SHALL be identical to the pre-change
behavior, and the golden baselines SHALL remain byte-identical.

#### Scenario: Schema default parity

- **WHEN** the schema defaults are compared against `DEFAULT_CONFIG`
- **THEN** every schema default equals the corresponding `DEFAULT_CONFIG` value

#### Scenario: No override means no change

- **WHEN** no profile override exists for a key
- **THEN** consumers read exactly the defaults they read before this change

### Requirement: Profile schema values

The schema SHALL cover provider settings, risk and sizing, stop and target,
analysis and signal gates, the paper cost model, notifications and schedule,
and reporting keys exactly as listed in the change proposal, each with a type
and either a numeric range or an explicit set of choices. Keys declared
operator-only (exchange access, safety caps, attestation, infrastructure,
data integrity, modeling, legacy paper fee keys) SHALL be rejected by the
profile setter.

#### Scenario: Out-of-range value rejected

- **WHEN** a saved value lies outside the declared range
- **THEN** the setter refuses the value and keeps the previous one

#### Scenario: Operator-only key rejected

- **WHEN** an update for `exchange_access_profile` or any other excluded key
  is requested through the profile
- **THEN** the request is rejected

### Requirement: Encrypted key store

Exchange and data-provider keys SHALL be stored encrypted, one `Fernet` token
per value, in `runs/profile_keys.enc.json`, written atomically with 600-style
permissions where the OS supports them; the file SHALL never contain
plaintext, secrets SHALL never appear in `config.json`, logs, error text, or
chat history, and saving SHALL fail when no encryption password is available.

#### Scenario: Secret round-trip

- **WHEN** a key is saved and then decrypted with the same encryptor
- **THEN** the plaintext matches and no plaintext exists on disk

#### Scenario: Missing encryptor refuses the save

- **WHEN** `SECRET_ENCRYPTION_PASSWORD` is absent
- **THEN** saving a key fails with an explicit message and nothing is written

### Requirement: Telegram profile menu

`/start` SHALL show a third button `⚙️ Profile`; submenus (callback prefix
`pf:`) SHALL cover exchange keys, service keys, risk, stop and target,
analysis, notifications and schedule, paper and costs, reporting, and reset
to defaults. Every callback and text input SHALL pass the admin check first.
Each parameter row SHALL show the current value and whether it is the
default; choice and boolean parameters SHALL use buttons, other types SHALL
use a pending text input that expires after 120 seconds, with a Cancel
button and a per-parameter reset-to-default button. Text without a pending
action SHALL receive the existing "Please use /start" answer.

#### Scenario: Non-admin is ignored

- **WHEN** a non-admin chat taps a profile callback
- **THEN** no profile state changes and the chat is told it is not authorized

#### Scenario: Expired pending input

- **WHEN** text arrives more than 120 seconds after the request
- **THEN** the input is ignored as if no pending action existed

### Requirement: Secret entry flow

For exchange keys the menu SHALL page venues eight per page, then ask for
sandbox or live, then the field, then request the key; the user's message
SHALL be deleted immediately via `delete_message`, a failed deletion SHALL
prompt "Delete the message manually" while keeping the saved key, the venue
SHALL be removed from `exchange_attested_keys`, and only the set/missing
status SHALL be echoed — never the value.

#### Scenario: Key saved

- **WHEN** an admin sends an API key to a pending field request
- **THEN** the message is deleted, the encrypted value is stored, the venue
  loses its attestation, and the reply shows status only

#### Scenario: Deletion failure still stores

- **WHEN** `delete_message` fails
- **THEN** the admin is told to delete the message manually and the key
  stays stored

### Requirement: Apply semantics

Profile values SHALL be read at call time wherever the code allows it. Risk
limits SHALL update the existing `RiskManager.config` fields in place because
`PaperTradingEngine` holds that reference. Saving an exchange key SHALL
invalidate cached permission verdicts and reconciliation state for that
venue. `initial_cash` and other startup-cached values SHALL be reported as
"applies after restart", and the paper ledger is never reset.

#### Scenario: Risk change applied live

- **WHEN** a risk limit is saved
- **THEN** the existing risk manager evaluates the new limit without a restart

#### Scenario: Key rotation rebuilds the gateway inputs

- **WHEN** a venue key is saved
- **THEN** the next submission loads credentials again and rebuilds the gate
  for that venue

### Requirement: Attestation is removal-only

The profile SHALL remove a venue from `exchange_attested_keys` whenever any
of its keys is saved or deleted, and SHALL never add a venue to that list.

#### Scenario: No attestation via profile

- **WHEN** keys are saved through the profile
- **THEN** no code path adds the venue to `exchange_attested_keys`
