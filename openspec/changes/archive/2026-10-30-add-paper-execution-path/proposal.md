# Proposal: add-paper-execution-path

Approval: approved by YT-IMPL-SPEC Revision 2.0 (2026-10-29), decisions G1,
G9 and G10.

## Why

`README.md` states that the default paper mode runs through
`TradingService.execute_signal(signal, mode="paper")`, and the `/paper`
command calls that method, but no definition exists in the source. The paper
engine is constructed and never used, `fill_order`,
`resolve_position_with_candles` and `update_positions` have no production
caller, and `open issues` records that `/paper` raises `AttributeError`
today. Cost and fill changes therefore have no effect in production.

## What Changes

- `TradingService.execute_signal(signal, mode="paper")` implements the
  documented contract: mode whitelist, kill switch, duplicate guard, last
  closed candle, mark prices, risk sizing, fill, persistence.
- `TradingService.resolve_open_paper_positions(now)` resolves open positions
  through the domain resolver on a time-range candle fetch.
- Two append-only tables, `paper_positions_opened` and
  `paper_positions_closed`, persist the position lifecycle; the service
  rehydrates open positions at startup.
- `MainApp.run` starts a paper resolution loop when
  `paper_execution_enabled` is true, independent of the outcome
  notification policy.
- An AST guard proves the paper path never imports the exchange layer.

## Impact

- Affected specs: `paper-execution`
- Affected code: `services/trading_service.py`, `trading/paper_trading.py`,
  `trading/ledger.py`, `app/telegram_bot.py`, `main.py`,
  `config/settings.py`
- Operator-visible: `/paper` executes in paper mode for the first time.
- Kill switch: `paper_execution_enabled` (default `true`).
