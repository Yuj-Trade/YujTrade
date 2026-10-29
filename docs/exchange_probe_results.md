# Exchange probe results

Read-only probe of the public venue API. No order is sent and no credential is
used. The agent has no venue network access, so the table is empty until the
operator runs the probe on the operator machine:

```text
python scripts/probe_exchanges.py
```

The script writes `runs/exchange_probe.json` and never places an order.

Status: `blocked_by_operator` — no row is filled in by the agent.

## Results

| exchange_id | load_markets | BTC/USDT | ticker | sandbox | ccxt_version | date |
|---|---|---|---|---|---|---|
| _operator fills this_ | | | | | | |

## Pre-verified facts from ccxt 4.5.90 (no network needed)

These come from inspecting the pinned client, not from a live probe. They
record what the sandbox switch does without contacting a venue.

| exchange_id | `set_sandbox_mode(True)` | sandbox_expected in registry | note |
|---|---|---|---|
| binance | supported | True | `testnet.binance.vision` |
| bybit | supported | True | testnet and demo |
| okx | supported | True | demo header |
| phemex | supported | True | `testnet.phemex.com` |
| bullish | supported | True | `api.simnext.bullish-test.com` |
| deribit | supported | True | `test.deribit.com`, derivatives only |
| kucoin | raises `TypeError` | True | no `urls.test` entry in this version |
| kraken | n/a | False | spot has no testnet; only the order `validate` parameter |
| lbank | n/a | False | `supplement/create_order_test` only, not a sandbox |
| coinbase | not verified | None | probe required |
| others | not verified | None | probe required |

## How to fill this table

1. Run the probe command above.
2. Open `runs/exchange_probe.json`.
3. Copy one row per venue into the table: `load_markets`, `btc_usdt`,
   `ticker`, `sandbox`, the recorded `ccxt_version` and the run date.
4. If a registry `sandbox_expected` value of `None` now has a real answer, update
   `trading/exchanges/registry.py` in its own commit with the reason in
   `ADR-0011`.
