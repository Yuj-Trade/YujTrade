# Tasks: add-signal-outcome-notifications

- [x] 0.1 Record the golden hashes in `tests/golden/golden.sha256` and run
      the baseline gate
- [x] 0.2 Write `proposal.md`, `tasks.md`, `design.md` and
      `specs/outcome-notifications/spec.md`
- [x] 0.3 `openspec validate add-signal-outcome-notifications --strict` is
      green
- [x] 0.4 The owner approved the proposal; the stages 1 to 9 were executed
      and the stage 10 was left out

## 1. Red tests

- [x] 1.1 `test_reopened_open_signal_keeps_first_creation_and_levels` (D1)
- [x] 1.2 `test_rotation_never_drops_protected_entries` (D2)
- [x] 1.3 `test_corrupt_history_is_backed_up_not_overwritten` (D3)
- [x] 1.4 `test_save_failure_leaves_previous_file_intact` (D3)
- [x] 1.5 `test_target_before_expiry_is_observed` (D4)
- [x] 1.6 `test_expired_signal_settles_without_analysis_cycle` (D5)
- [x] 1.7 `test_prune_keeps_resolved_entry_with_open_notification` (D6)
- [x] 1.8 The six defects are pinned with
      `@pytest.mark.xfail(strict=True, reason="D<n>")`
- [x] 1.9 The characterization tests stay green: the reconciliation settles
      an expired signal without an outcome and sets it with `resolve`, and
      `get_performance_summary` counts the resolved and the pending entries

## 2. Atomic persistence (D3)

- [x] 2.1 `write_text_atomic(path, text)` at module level in
      `strategy/signal_tracker.py`
- [x] 2.2 `_save_history` serialises inside the lock and hands only the
      string to the thread; `_save_history_sync` is removed
- [x] 2.3 `_load_history` backs an unreadable file up to
      `signal_history.corrupt-<UTC timestamp>.json` and returns `{}`
- [x] 2.4 `test_corrupt_history_is_backed_up_not_overwritten`,
      `test_save_failure_leaves_previous_file_intact` and
      `test_history_roundtrip_is_byte_stable` are green

## 3. Protected entries (D1, D2, D6)

- [x] 3.1 `record_if_absent(signal_id, details)` and its use in
      `TradingService.analyze_symbol`; `record` and
      `update_resolution_details` are unchanged
- [x] 3.2 `_is_protected(data)` at module level
- [x] 3.3 The rotation only moves the unprotected entries, oldest first, and
      warns when it cannot free enough slots
- [x] 3.4 The pruning keeps the protected entries
- [x] 3.5 The three defect tests leave the `xfail` state and are green
- [x] 3.6 `test_record_if_absent_returns_false_for_existing_open_signal`
      and `test_rotation_moves_only_settled_entries_to_rotated_file` are
      green
- [x] 3.7 The performance report over a fixed ledger is byte-identical
      before and after this commit

## 4. The pure core

- [x] 4.1 `_first_barrier_hit` extracted without a behaviour change
- [x] 4.2 `EVENT_KINDS`, `OutcomeEvent` and `event_from_resolution`
- [x] 4.3 `observe_signal_barrier`
- [x] 4.4 The tests of `tests/unit/domain/test_outcome_edges.py` cover the
      target, the stop, the shared candle, the open candle, the late first
      candle, the invalid arguments and a randomised parity against
      `resolve_signal_outcome`

## 5. Policy, message and port

- [x] 5.1 `application/outcome_ports.py` with `OutcomeNotifier` and
      `NotificationDeliveryError`
- [x] 5.2 `application/outcome_policy.py` with `NotificationPolicy`,
      `build_policy`, `is_eligible` and `failure_state`
- [x] 5.3 `application/outcome_message.py` with `render_outcome`
- [x] 5.4 `tests/unit/application/test_outcome_policy.py` and
      `test_outcome_message.py`

## 6. The notification state API of the tracker (D4 at the data level)

- [x] 6.1 `set_outcome_event`, `open_signals`, `due_notifications`,
      `claim_notification`, `complete_notification` and
      `fail_notification`
- [x] 6.2 The state tests in `tests/unit/strategy/test_signal_tracker.py`

## 7. Observation and settlement (D4, D5)

- [x] 7.1 `_settle_expired` extracted from `reconcile_pending_signals`, which
      records the outcome event
- [x] 7.2 `watch_outcomes` and `_watch_group` with a bounded concurrency
      and one fetch per symbol and timeframe group
- [x] 7.3 The watch never changes the outcome and never writes the ledger
- [x] 7.4 `tests/unit/services/test_outcome_watch.py`

## 8. Delivery, the run loop and the scheduler store

- [x] 8.1 `services/outcome_dispatch.py` with `dispatch_outcomes`
- [x] 8.2 `TelegramOutcomeNotifier` in `app/telegram_bot.py` with the
      documented error mapping
- [x] 8.3 The shared `SchedulerStore` in `main.py` and the
      `_outcome_watch_loop`
- [x] 8.4 `tests/unit/services/test_outcome_dispatch.py` and
      `tests/unit/app/test_telegram_outcome_notifier.py`
- [x] 8.5 `tests/unit/test_main_startup.py` stays green: no `OutcomeWatch`
      task in the off mode, an invalid configuration is logged and does not
      stop the bot

## 9. Configuration, metrics and documentation

- [x] 9.1 The eight configuration keys in `ConfigManager.DEFAULT_CONFIG`
- [x] 9.2 The two counters and the two recorder functions in
      `common/metrics.py`
- [x] 9.3 `README.md`, `docs/architecture.md`, `docs/runbook.md`,
      `docs/open_issues.md` and
      `docs/adr/ADR-0010-signal-outcome-notifications.md`
- [x] 9.4 The full gate, the slow gate and the golden hashes are green

## 10. Optional, only with an explicit approval

- [x] 10.1 The `/outcomes` command with the existing `_is_admin` guard
- [x] 10.2 The output tests in `tests/unit/app/test_command_guards.py` and a
      new test file for the content
