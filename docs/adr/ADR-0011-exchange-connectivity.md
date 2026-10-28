# ADR-0011: Exchange connectivity for spot limit orders

Status: accepted

Operator approval was recorded from the one-shot input of the run that created
this ADR on 2026-10-29.

## Context

YujTrade produced signals but executed nothing outside the paper engine. The
operator wants the confirmed signal to reach a real venue, for spot limit
orders only, long-only, with paper and sandbox as the default state.

The prior adapter, `trading/execution.py:ExchangeAdapter`, failed open. With
`dry_run=False` and no exchange it returned a fabricated success; a missing
order id was replaced by a random uuid; a missing `filled` field was treated as
a full fill; and the fee was estimated from a configured rate instead of read
from the venue. `ExecutionEngine` records `FILLED` for any accepted answer,
which mislabels a resting limit order.

Twelve venues in the requested list would receive real money if a mistake were
made, so the gate has to be reviewable in one place and every ambiguous answer
has to leave the order unresolved instead of guessed.

## Decision

### 1. `ccxt` is the venue client, pinned exactly

`requirements.txt` pins `ccxt==4.5.90`. The version was selected from PyPI,
installed in the local environment, and inspected before any code was written.
`requirements.lock` is not edited by hand; it is refreshed by the
`lock-refresh` workflow on the operator machine (recorded in
`docs/open_issues.md`).

Every ccxt symbol used is checked against the pinned version:

- Every `ccxt_id` in `trading/exchanges/registry.py` resolves to a class in
  `ccxt.async_support` except Ourbit, which has no ccxt class.
- Every gateway method (`fetch_ticker`, `fetch_order_book`,
  `amount_to_precision`, `price_to_precision`, `fetch_balance`,
  `fetch_open_orders`, `fetch_closed_orders`, `create_order`,
  `fetch_trading_fee`, `request`, `describe`, `load_markets`, `close`,
  `set_sandbox_mode`) exists on all 21 ccxt-backed classes.
- `Exchange.request` has the signature
  `(path, api=["public"], method="GET", params={}, config={})`, so the
  permission check passes the API section as the second positional argument.

### 2. The registry carries the venue list, nothing else does

`trading/exchanges/registry.py` holds the 22 frozen `ExchangeSpec` values.
A difference between the playbook and the pinned ccxt version is resolved in
favour of what was verified, recorded here, and corrected in the registry in
its own commit.

### 3. Three layers, one decision surface

- `domain/exchange_types.py` holds the statuses, the terminal sets and the
  three frozen dataclasses. Standard library only.
- `application/exchange_ports.py` defines the `ExchangeGateway` protocol.
- `application/exchange_policy.py` holds `submission_mode`, `risk_check`,
  `map_ccxt_status`, `next_status` and `scope_matches_profile` as pure
  functions over plain values.
- `trading/exchanges/` holds everything that touches `ccxt`.

### 4. Sandbox is documented per venue, not assumed per venue

The pinned version was probed for `set_sandbox_mode(True)` support:

| Venue | `set_sandbox_mode(True)` in 4.5.90 | Registry `sandbox_expected` |
|---|---|---|
| binance | supported | `True` |
| bybit | supported | `True` |
| okx | supported | `True` |
| phemex | supported | `True` |
| bullish | supported | `True` |
| deribit | supported (`test.deribit.com`) | `True` |
| kucoin | raises `TypeError` (no `urls.test` entry) | `True` |
| kraken | spot has no testnet; only the `validate` order parameter | `False` |
| lbank | sandbox absent; `supplement/create_order_test` exists | `False` |
| coinbase | not verified | `None` |
| others | not verified | `None` |

Where the registry expects a sandbox and the client cannot provide one, the
gateway raises `ExchangeConfigError("sandbox_not_supported")` instead of
silently talking to production.

### 5. The LBank permission endpoint is `supplement/api_Restrictions`

The playbook names `v2/supplement/api_Restrictions.do`. In ccxt 4.5.90 the
LBank private `spot` API exposes `supplement/api_Restrictions` and the client
already prefixes the version, so the registry now records
`supplement/api_Restrictions`.

The response fields of that endpoint were not verified against official LBank
documentation during this run. Until they are, the LBank permission rule is
undefined: `verify_key_permissions` returns
`(False, "lbank_rule_not_defined")` and LBank can never reach the live mode.

### 6. `lbank2` does not exist in the pinned version

The playbook assumed a newer `lbank2` class. In ccxt 4.5.90 the `lbank` class
reports `version == "v2"`, so `lbank` **is** the v2 client and the registry
records `ccxt_id == "lbank"`. There is no second class to fall back to.

### 7. Every ambiguous submission is left unresolved

A network error or a timeout leaves the row in `pending_submit`. No retry is
issued. Reconciliation moves the row forward, or marks it `unknown` once it is
older than `exchange_unknown_after_seconds`. The terminal statuses (`filled`,
`canceled`, `rejected`, `expired`, `shadow`) are never rewritten by any path.

### 8. Live needs seven independent conditions and a second confirmation

`submission_mode` returns `live` only when all of these hold:
`execution_dry_run` is false, `exchange_sandbox` is false,
`exchange_live_enabled` is true, `exchange_live_review_id` names an ADR file
whose `Status:` line says `accepted`, the venue is in
`exchange_attested_keys`, `permissions_ok` is true, and the access profile
matches. The request itself additionally needs a one-time code from
`/exchange_confirm`, valid for 60 seconds and usable once.

### 9. Shadow soak exit criteria

A venue may reach live only after a 14-day shadow period on the operator
machine with all of these true:

- Zero `exchange_not_ready` rows.
- Zero `key_not_attested` rows.
- No price deviation outside `exchange_max_price_deviation_pct`.
- No `unknown` row left unexplained.

## Consequences

- The venue list, the sandbox expectations and the permission endpoints are
  auditable in one file.
- A wrong assumption about a venue now produces a refusal, not an order.
- Shadow mode lets the operator observe a venue without an order.
- Lan and Ourbit are reachable only under the `iran` profile.
- The paper path is untouched: `PaperTradingEngine`, `/paper` and
  `runs/paper_ledger.db` keep their behavior.
- `ExecutionEngine` remains uncalled from any runtime path; the new path is
  `trading/exchanges/execution_service.py`.

## References

- Playbook `yujtrade_exchange_agent_playbook_v2.md` (sections 4, 6, 7, 12, 17).
- `openspec/changes/add-exchange-connectivity/design.md`.
- `docs/adr/ADR-0012-exchange-access-profiles.md`.
- `docs/exchange_probe_results.md`.
- `docs/operator_pending.md`.
