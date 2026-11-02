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

Plus the runtime confirmation: `/exchange_execute <venue> <signal_id>` returns a
one-time code, and the same command repeated with that code within 60 seconds
places the order. The code is consumed only after the risk checks pass.

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

## 10. Continuous learning enablement (2026-10-29)

- Status: `blocked_by_operator`.
- Action: run `python scripts/train_models.py` on the operator machine (it
  needs market data), then run
  `python scripts/review_learning_artifacts.py`. It writes
  `docs/remediation/learning-review-2026-10-29.md` and exits `0` only when
  every current artifact verifies and at least one exists.
- Then: enable learning locally by setting `model_learning.enabled` to
  `true` in the untracked `config.json` (keep every other `model_learning`
  key; never write a secret). `config.json` is gitignored and is never
  committed.
- Why blocked: this machine has no `artifacts/` tree, so the review exits
  `1` and the committed default stays `false` (decision G4).
- Evidence: `{"exit_code": 1, "artifacts": 0}` from
  `python scripts/review_learning_artifacts.py`.

## 11. Exchange remediation v4 open items (2026-11-02)

Status: `blocked_by_operator`. None of these were implemented in the v4 run.

- I-03 balance and fee reconciliation: define the comparison baseline (starting
  balance or a change report) then wire it. Not implemented.
- I-04 client order id support: verify each venue's official documentation for
  the length and format of the client order id before setting
  `client_id_supported=True` for any venue.
- I-05 LBank permission rule: still undefined (see section 8).
- I-06 Ourbit: still needs official API documentation (see section 7).
- I-07 sandbox expectations: run `python scripts/probe_exchanges.py` on the
  operator machine and record results in `docs/exchange_probe_results.md`.
- L-05 sizing reference price: decide entry vs last close. This run changed
  nothing.
- L-06 older signals via `/exchange_execute`: decide whether sending a signal id
  that is not in a fresh analysis should be allowed.
- Operator tasks unchanged from sections 1-10: probe, key attestation,
  lock-refresh, a real sandbox run, the 14-day soak, written acceptance of
  ADR-0011 and ADR-0012 and the terms-of-use statement, and live activation with
  a human review.
