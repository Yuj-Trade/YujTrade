# Ourbit API inventory

Status: `blocked_by_operator` — official Ourbit API documentation was not
located from this environment. This file is a template, not a specification.
No endpoint is implemented and no request is sent to Ourbit.

## What must be filled before any code exists

| Item | Value (operator fills) | Verified against official docs (date, URL) |
|---|---|---|
| Base REST host | | |
| Auth scheme (HMAC-SHA256 / RSA / other) | | |
| Signed parameter order and encoding | | |
| Timestamp / recvWindow rule | | |
| API key header or query parameter name | | |
| Passphrase required | | |
| Ticker endpoint | | |
| Order book endpoint | | |
| Symbol format (`BTC/USDT` or `BTC_USDT`) | | |
| Create limit order endpoint and body | | |
| Client order id field name | | |
| Cancel order endpoint | | |
| Open orders endpoint | | |
| Closed orders endpoint | | |
| Balance endpoint | | |
| Key permission (withdrawal) endpoint | | |
| Rate limit rules | | |
| Signature test vector from the docs | | |

## Promotion procedure

`trading/exchanges/factory.py:build_gateway` raises `OurbitNotReady` while the
registry status is `pending_docs_verification`. Promotion requires, in order:

1. Each row above filled from the official documentation with its URL and date.
2. An endpoint inventory written here, with no guessed endpoint.
3. `trading/exchanges/ourbit_gateway.py` implementing only those endpoints and
   satisfying `application.exchange_ports.ExchangeGateway`.
4. A signature implementation validated against the test vector from the
   documentation. Without a test vector, Ourbit does not become ready.
5. An addendum to `docs/adr/ADR-0012-exchange-access-profiles.md` linking the
   documentation and the review date.
6. The registry `status` changed to `ready` in its own commit.

Until all six hold, the venue stays listed as `pending_docs_verification` and
the `iran` profile does not make it reachable for orders.
