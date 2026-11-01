## Why

YujTrade currently resolves, ranks and reports trading signals, and executes them
only through the in-process paper engine. There is no way to route a confirmed
signal to a real exchange without hand-placing the order, and the one adapter
that exists (`trading/execution.py:ExchangeAdapter`) fails open: it fabricates a
successful order when the exchange is missing and assumes a full fill when the
venue reports none.

The operator asked for exchange connectivity: 22 venues in a registry, spot
limit orders only, long-only, paper and sandbox by default, and no live order
without an explicit operator activation.

Status: pending approval.

The operator has not confirmed this proposal in writing. The status changes to
approved only after an explicit written confirmation from the operator in the
conversation. The earlier text that recorded a one-shot approval is withdrawn;
the operator's chat contains no such statement.

## What Changes

- Adds a frozen exchange registry of 22 venues with an access scope
  (`general` or `iran_users_only`), a readiness status, sandbox expectations,
  passphrase requirements, secret encodings and an optional key-permission
  endpoint.
- Adds pure domain types (`domain/exchange_types.py`), an `ExchangeGateway`
  protocol (`application/exchange_ports.py`) and a pure policy module
  (`application/exchange_policy.py`) that decides submission mode, status
  mapping and risk rejection reasons.
- Adds encrypted credential loading for `<PREFIX>_API_KEY`,
  `<PREFIX>_API_SECRET`, `<PREFIX>_API_PASSPHRASE` and their `SANDBOX`
  variants, decrypting only `ENCRYPTED_<NAME>` values. A plaintext value in
  `.env` disables the credentials instead of silently working.
- Adds a read-only `ccxt` gateway for public market data and a read-only
  authenticated path for balances and orders.
- Adds a live ledger (`runs/live_ledger.db`) with a unique `signal_id`, a
  terminal-status lock, and a reconciliation pass that never re-sends an order.
- Adds `ExchangeExecutionService`, the single decision path from a signal to a
  venue, gated by halt state, exchange enablement, scope profile, credentials,
  shadow mode, sandbox mode, dry-run, live enablement, review id and key
  attestation.
- Adds administrator Telegram commands: `/exchanges`, `/exchange_status`,
  `/exchange_execute`, `/exchange_halt` and `/exchange_resume`. A live execution
  is confirmed by repeating `/exchange_execute` with the one-time code the bot
  returns.
- Fixes the fail-open `ExchangeAdapter` (missing exchange, missing order id,
  unknown fill, estimated fee, limit order recorded as `FILLED`).
- Adds shadow mode and a shadow report script, so a venue can be observed for
  14 days without any order.
- **BREAKING**: `ExchangeAdapter.create_order` in a non dry-run path now
  returns `ok=False` instead of a fabricated success when the venue does not
  answer completely. Any caller relying on the synthetic order id breaks;
  `ExecutionEngine` is not called from any runtime path.

## Impact

- Affected specs: `exchange-connectivity` (new capability).
- Affected code: `domain/exchange_types.py`, `application/exchange_ports.py`,
  `application/exchange_policy.py`, `trading/exchanges/*`,
  `trading/live_ledger.py`, `trading/reconciliation.py`,
  `trading/execution.py`, `config/settings.py`, `config/logger.py`,
  `scripts/encrypt_keys.py`, `scripts/probe_exchanges.py`,
  `scripts/exchange_shadow_report.py`, `services/trading_service.py`,
  `app/telegram_bot.py`, `common/metrics.py`, `requirements.txt`.
- Out of scope in this change: short selling, futures, any withdrawal or
  transfer call, `ccxt.pro` and WebSocket streams in the first version,
  automatic order re-submission, geographic workarounds, and any check of the
  operator's identity or residence.
- The model data path is unchanged: no `model_data_limits`,
  `LONG_TERM_CONFIG`, indicator formula or golden hash moves. Other venues are
  used only to control price and spread on the execution path.
