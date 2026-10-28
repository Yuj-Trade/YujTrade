# ADR-0012: Exchange access profiles

Status: accepted

Operator approval was recorded from the one-shot input of the run that created
this ADR on 2026-10-29. The operator also declared that the terms of use of the
accounts in use were reviewed by the operator.

## Context

The operator asked for 22 venues. Twenty are available to the accounts in
general use. LBank and Ourbit were added because the operator reports that the
other twenty venues do not accept users in Iran. That report is the
operator's, not a finding of this application.

An application cannot decide whether a particular account may trade on a
particular venue: that depends on the account's terms of use, the operator's
residence, the sanctions regime that applies and the venue's own enforcement.
The application must therefore carry the distinction without pretending to
verify it.

## Decision

### 1. Every venue carries an `access_scope`

`scope` is `general` or `iran_users_only`. It lives in
`trading/exchanges/registry.py` next to the venue, not in a list scattered
through the code.

### 2. Profiles are symmetric and mutually exclusive

`application/exchange_policy.py:scope_matches_profile` accepts:

- `general` scope with the `general` profile;
- `iran_users_only` scope with the `iran` profile;
- nothing else.

The `iran` profile therefore accepts only LBank and Ourbit. The `general`
profile therefore accepts neither. This is deliberate: a mixed profile would
make it easy to send a signal to a venue the operator did not intend.

### 3. The profile is operator configuration only

`exchange_access_profile` defaults to `general` in
`ConfigManager.DEFAULT_CONFIG`. Only the operator changes it, in the untracked
`config.json`. No Telegram command changes it and no code path derives it.

### 4. No identity, residence or sanctions check

The application does not read a passport, an address, an IP geolocation or an
account residency field. It does not detect the operator's location. It
implements no proxy, VPN, IP rotation, synthetic header or any other means to
work around a geographic restriction. `ADR-0011` and the runbook record that
eligibility is the operator's responsibility.

### 5. LBank

- `ccxt_id` is `lbank` after the version check documented in `ADR-0011`; the
  pinned client reports `v2`.
- `permission_endpoint` is `supplement/api_Restrictions`.
- `sandbox_expected` is `False`: LBank documents only an order-test endpoint
  (`supplement/create_order_test`), which is not a sandbox account.
- LBank therefore requires the probe and the shadow soak, and cannot reach the
  live mode until the response fields of `api_Restrictions` are verified and
  the permission rule is written into `ADR-0011`.

### 6. Ourbit

- `ccxt_id` is `None`: ccxt 4.5.90 has no Ourbit class.
- `status` is `pending_docs_verification`.
- No endpoint is implemented. `trading/exchanges/factory.py` raises
  `OurbitNotReady` and no request leaves the process.
- Promotion to `ready` requires, in this order: official API documentation, a
  written endpoint inventory in `docs/exchange_ourbit_api.md`, a gateway that
  uses only those endpoints, and a signature implementation validated against
  a test vector from that documentation. The registry change is its own commit
  with an addendum to this ADR.

### 7. Neither Iran venue gets a sandbox shortcut

Neither venue offers a sandbox account. Shadow mode is therefore the only
pre-live state, and the shadow soak in `ADR-0011` is mandatory.

## Consequences

- A single boolean gate decides reachability, so a misconfiguration can only
  narrow what is reachable, never widen it.
- The operator can run a `general` deployment and an `iran` deployment from the
  same code with different untracked configuration.
- LBank and Ourbit are visible in `/exchanges` with their scope, so the
  limitation is not hidden from the operator.
- No claim about legality, sanctions or account eligibility is made by the
  software.
