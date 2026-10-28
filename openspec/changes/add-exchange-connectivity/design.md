## Context

YujTrade is a signal bot whose execution path is paper only. `TradingService`
owns the quality pipeline and calls `PaperTradingEngine`. `ExecutionEngine` and
`ExchangeAdapter` exist but are never reached from a runtime path, and
`ExchangeAdapter` fails open.

The operator wants real exchange connectivity for spot limit orders. Three
things are fixed by the request: the venue list (22 entries), the access
profiles (`general` and `iran_users_only`), and the safety posture (paper and
sandbox by default, live activation only by the operator).

Layer contract (see `CLAUDE.md` and `tests/unit/test_architecture.py`):

- `domain/` imports the standard library only.
- `application/` imports `domain` and the standard library only.
- `ccxt` may be imported only inside `trading/exchanges/`.

## Goals / Non-Goals

- Goals: one decision surface for "may this signal go to this venue", a
  durable order record with a unique client order id, a reconciliation pass
  that never re-sends, and an operator-controlled live switch with a second
  confirmation.
- Non-Goals: short selling, futures, withdrawals, transfers, order editing
  that re-sends, WebSocket streams, `ccxt.pro`, automated re-entry after an
  ambiguous response, and any identity or residence verification.

## Decisions

### Decision: the gate is a pure function over booleans

`application/exchange_policy.py:submission_mode` takes a `GateInput` of plain
booleans and returns `(mode, reason)`. Callers gather the booleans from the
ledger, the config and the credential loader. This keeps the order of the
checks reviewable and unit-testable without a venue, a database or a network.

- Alternatives: a class holding mutable state per exchange. Rejected: it
  makes the ordering of the checks implicit and the tests stateful.

### Decision: the ledger is the only record of an order attempt

`trading/live_ledger.py` stores one row per `signal_id` and one row per
`(exchange_id, client_order_id)`, enforced by the schema. A row is written
*before* the request leaves the process, so a restart or a dropped response
still leaves a row that reconciliation can resolve. Terminal statuses
(`filled`, `canceled`, `rejected`, `expired`, `shadow`) are never rewritten.

- Alternatives: rely on the venue to list orders. Rejected: a venue query does
  not tell us which local signal produced the order, and not every venue
  returns a client order id in its listings.

### Decision: a network failure is never retried

`submit_signal` leaves the row `pending_submit` when a timeout or a network
error escapes. Reconciliation moves it forward or marks it `unknown`. A human
decides what happens next. This is stricter than a retry with an idempotency
key, because not every venue honours the key in the same way.

### Decision: `ccxt` is pinned and probed, never assumed

`ccxt` is pinned to an exact version. Every method used is checked against that
version before use. During implementation the pinned version (4.5.90) was
inspected and produced these findings, which override the playbook where they
differ:

| Item | Verified state in ccxt 4.5.90 | Consequence |
|---|---|---|
| `lbank2` class | absent | `lbank` reports `version == "v2"`, so `lbank` is the v2 class and the registry uses it |
| `lbank` permission endpoint | `spot/private/post` contains `supplement/api_Restrictions` | the registry value `v2/supplement/api_Restrictions.do` is corrected to `supplement/api_Restrictions` |
| `lbank` order test endpoint | `supplement/create_order_test` exists | documented for the operator, not used by the default path |
| `binance` permission endpoint | `sapi/v1/account/apiRestrictions` | registry value kept |
| `kucoin` sandbox | `set_sandbox_mode(True)` raises `TypeError` (no `urls.test`) | kuccoin sandbox is unsupported in this version; `sandbox_expected` remains `True` per the playbook but the gateway reports `sandbox_not_supported` |
| `coinbase` / `bullish` secrets | not verified as PEM | `secret_encoding` stays `base64` and the operator may switch to `plain` after inspection |
| `coinbase` permission endpoint | absent | `None`, so human attestation is mandatory |
| `deribit` | `spot_supported` is false in the registry | never traded, per the playbook |

### Decision: secrets are encrypted or absent

Only `ENCRYPTED_<NAME>` values are accepted for exchange keys.
`SecretsManager.get_exchange_secret` never falls back to the plaintext name.
A leftover plaintext value is detected by
`trading/exchanges/credentials.py:find_plaintext_exchange_secrets`, which
returns names only and forces `credentials_ok` to false.

The `.env` file carries the key names with empty values so the operator knows
exactly which variables to fill; the values themselves stay outside the
repository.

### Decision: LBank and Ourbit are scoped to the Iran profile

`scope_matches_profile` is symmetric: the `iran` profile accepts only
`iran_users_only` venues and the `general` profile accepts only `general`
venues. Ourbit stays `pending_docs_verification` until official API
documentation exists; its gateway raises `OurbitNotReady` and no request is
made.

## Risks / Trade-offs

- Risk: a venue accepts an order but never answers. Mitigation: the row is
  written first, the status stops at `pending_submit`, and reconciliation
  raises `unknown` after `exchange_unknown_after_seconds`.
- Risk: a key secretly carries withdrawal rights. Mitigation: the permission
  endpoint is queried when the venue documents one, and attestation is
  mandatory everywhere else.
- Risk: an operator enables live with the wrong review id. Mitigation:
  `review_is_accepted` requires an ADR file on disk whose status is
  `accepted`, and a live submission additionally needs a one-time code.
- Risk: the Iran venue list is mistaken for a compliance claim. Mitigation:
  `ADR-0012` states that account eligibility is the operator's
  responsibility and the application performs no check.
- Trade-off: an ambiguous response leaves an order in `unknown` until a human
  looks. Accepted, because a double fill is worse than a manual check.

## Migration Plan

1. Merge the gates and the ledger with everything disabled
   (`exchange_enabled` empty, `exchange_sandbox` true, `exchange_shadow_mode`
   true, `exchange_live_enabled` false).
2. Operator runs the probe and records the results.
3. Operator encrypts sandbox keys and runs the shadow soak.
4. Operator activates live for one venue, with a review id and attestation.
5. Rollback: empty `exchange_enabled` and set `exchange_live_enabled` false.
   The ledger and the paper paths are independent, so no paper data moves.

## Open Questions

- The official Ourbit API documentation was not located during this run, so
  its gateway and its registry status stay pending.
- The LBank `api_Restrictions` response fields were not verified against
  official documentation, so the LBank permission rule stays undefined and
  LBank never goes live until the rule is written into this ADR.
