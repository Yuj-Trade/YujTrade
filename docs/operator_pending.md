# Operator pending

Everything in this file is blocked on the operator machine. The agent delivered
code, offline tests and the commands; none of these items were executed during
the automated run because they need venue network access, a real key or an
operator decision.

Status key: `blocked_by_operator`.

## 1. Probe (read-only, no keys)

- Command: `python scripts/probe_exchanges.py`
- Writes: `runs/exchange_probe.json`
- Then: copy the result into `docs/exchange_probe_results.md`
- Why blocked: the agent has no venue network access.

## 2. Key attestation

- Action: fill `exchange_attested_keys` in `config.json` with the venues whose
  keys were confirmed to carry no withdrawal right.
- Why blocked: attestation is a human statement about a key the agent never
  sees.

## 3. Requirements lock refresh

- Action: run the `lock-refresh` workflow on the operator machine.
- Why blocked: `requirements.lock` must not be edited by hand; only the
  workflow regenerates it.
- Note: `requirements.txt` is already pinned to `ccxt==4.5.90`; the lock still
  needs the refresh.

## 4. Sandbox tests

- Command: `YUJTRADE_SANDBOX_TESTS=1 python -m pytest -m sandbox -q`
- Requirements: sandbox keys in `.env`, encrypted with
  `python scripts/encrypt_keys.py`.
- After the run: revoke the sandbox keys at the venue.
- Why blocked: needs a real sandbox key and network access.

## 5. Shadow soak (14 days)

- Command: `python scripts/exchange_shadow_report.py` at the end of the period.
- Exit criteria: `docs/adr/ADR-0011-exchange-connectivity.md` section 9.
- Why blocked: a calendar period on the operator machine.

## 6. Live activation

Seven conditions, all set by the operator in `config.json`:

1. `execution_dry_run` = false
2. `exchange_sandbox` = false
3. `exchange_live_enabled` = true
4. `exchange_live_review_id` = `ADR-0011`
5. the venue is in `exchange_attested_keys`
6. the permission check passes, or the venue has no permission endpoint and the
   attestation covers it
7. the venue scope matches `exchange_access_profile`

Plus the runtime confirmation: `/exchange_execute <venue> <signal_id>` followed
by `/exchange_confirm <code>` within 60 seconds.

- Why blocked: this is the operator's explicit, manual activation. The agent
  writes no live value anywhere.

## 7. Phase 12 Ourbit

- Step 1 (documentation discovery) was not completed: official Ourbit API
  documentation was not located, so the endpoint inventory in
  `docs/exchange_ourbit_api.md` is a template, not a specification.
- Blocked steps: endpoint inventory, gateway, signature test vector, registry
  promotion, all `blocked_by_operator`.
- LBank and the `iran` profile are delivered and tested offline; they do not
  depend on Ourbit.

## 8. LBank permission rule

- Action: read the official LBank documentation for
  `supplement/api_Restrictions` and write the response rule into `ADR-0011`.
- Until then: `verify_key_permissions` returns
  `(False, "lbank_rule_not_defined")` and LBank never reaches live.

## 9. Coinbase and Bullish secret encoding

- Action: inspect a real key. If it is a single line, change
  `secret_encoding` from `base64` to `plain` in the registry and update
  `ADR-0011`.
- Why blocked: the agent never sees a key.
