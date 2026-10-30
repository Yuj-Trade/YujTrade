## 1. Execution (P4)
- [x] 1.1 `TradingService.execute_signal` with the mode whitelist and the kill switch
- [x] 1.2 `PaperLedger.has_order` duplicate guard
- [x] 1.3 `paper_positions_opened` / `paper_positions_closed` and their triggers

## 2. Resolution and restart (P4)
- [x] 2.1 `TradingService.resolve_open_paper_positions`
- [x] 2.2 Startup rehydration
- [x] 2.3 `_paper_resolution_loop` in `MainApp.run`

## 3. Command and guards (P4)
- [x] 3.1 `paper_command` isolates one failing signal
- [x] 3.2 `tests/unit/services/test_paper_execution.py`
- [x] 3.3 `tests/unit/trading/test_paper_execution_guard.py`
