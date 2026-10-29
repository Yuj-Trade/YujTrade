# Proposal: add-intrabar-outcome-port

Approval: approved by YT-IMPL-SPEC Revision 2.0 (2026-10-29), decisions G1
and G5.

## Why

The outcome notification is only raised on a closed candle, so the inherent
delay is the candle duration plus the watch interval: a target touched
inside a one-hour candle is reported after that candle closes, and a `1d`
signal is reported up to a day later. The data provider offers no intrabar
price stream, so the delay cannot be removed today, but the seam should be
reserved so a future feed does not touch the domain or the loop.

## What Changes

- `application/outcome_ports.py` gains an `IntrabarPriceFeed` protocol with
  `last_price(symbol)`.
- `data/intrabar_feed.py` provides `NullIntrabarPriceFeed`, which returns
  `None`.
- Nothing is wired to the outcome watch; the delivery stays on closed
  candles.
- ADR-0010 records the deferral and the current latency.

## Impact

- Affected specs: `outcome-notifications`
- Affected code: `application/outcome_ports.py`,
  `data/intrabar_feed.py` (new), `docs/adr/ADR-0010-*`
- No behaviour change; open issue 15 is marked deferred.
