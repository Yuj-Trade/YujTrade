## 1. Phase 1: baseline and existing bug fixes

- [x] 1.1 Record the baseline gate result and the golden hashes
- [x] 1.2 Pin `ccxt` to an exact version in `requirements.txt`
- [x] 1.3 Make `ExchangeAdapter` fail closed in the non dry-run path
- [x] 1.4 Add `tests/unit/trading/test_exchange_adapter_fail_closed.py`

## 2. Phase 2: pure domain, ports, policy and registry

- [x] 2.1 Add `domain/exchange_types.py`
- [x] 2.2 Add `application/exchange_ports.py`
- [x] 2.3 Add `application/exchange_policy.py`
- [x] 2.4 Add `trading/exchanges/registry.py` with the 22 venues
- [x] 2.5 Add domain, policy, registry and no-withdraw tests

## 3. Phase 3: encrypted exchange secrets

- [x] 3.1 Add `SecretsManager.get_exchange_secret` with no plaintext fallback
- [x] 3.2 Add `trading/exchanges/credentials.py`
- [x] 3.3 Merge registry secret names into `scripts/encrypt_keys.py`
- [x] 3.4 Extend the log redaction pattern
- [x] 3.5 Add `trading/exchanges/errors.py` with `sanitize`
- [x] 3.6 Add credential tests including a log-leak test

## 4. Phase 4: read-only market data gateway

- [x] 4.1 Add `trading/exchanges/ccxt_gateway.py` (public methods)
- [x] 4.2 Add `trading/exchanges/factory.py`
- [x] 4.3 Add `scripts/probe_exchanges.py`
- [x] 4.4 Add offline gateway tests with a fake client

## 5. Phase 5: authenticated reads and key permission check

- [x] 5.1 Add `fetch_free_balance` and `fetch_order_by_client_id`
- [x] 5.2 Add `verify_key_permissions`
- [x] 5.3 Add permission-check tests with fixtures

## 6. Phase 6: live ledger and reconciliation

- [x] 6.1 Add `trading/live_ledger.py`
- [x] 6.2 Add `trading/reconciliation.py`
- [x] 6.3 Add ledger, restart and unknown-status tests

## 7. Phase 7: sandbox order submission

- [x] 7.1 Add `trading/exchanges/gate_inputs.py`
- [x] 7.2 Add `trading/exchanges/execution_service.py`
- [x] 7.3 Implement `place_limit_order` in the gateway
- [x] 7.4 Add the exchange keys to `ConfigManager.DEFAULT_CONFIG`
- [x] 7.5 Wire the service in `create_trading_stack` and `TradingService`
- [x] 7.6 Add submission tests with a fake gateway

## 8. Phase 8: administrator Telegram controls

- [x] 8.1 Add `/exchanges` and `/exchange_status`
- [x] 8.2 Add `/exchange_execute`, `/exchange_halt` and `/exchange_resume`
- [x] 8.3 Add non-admin and no-secret-leak tests

## 9. Phase 9: shadow mode

- [x] 9.1 Keep shadow mode free of any `place_limit_order` call
- [x] 9.2 Add `scripts/exchange_shadow_report.py`
- [x] 9.3 Add the shadow test with a call counter

## 10. Phase 10: live activation mechanism

- [x] 10.1 Add the one-time confirmation code flow
- [x] 10.2 Add the activation checklist to `docs/runbook.md`
- [x] 10.3 Add gate tests covering every incomplete condition
- [x] 10.4 Record the operator-only steps in `docs/operator_pending.md`

## 11. Phase 11: further general venues

- [x] 11.1 Document the probe procedure and results table
- [x] 11.2 Isolate per-venue quirks inside `ccxt_gateway.py`

## 12. Phase 12: Iran access profile

- [x] 12.1 Correct the LBank `ccxt_id` to the verified v2 class
- [x] 12.2 Keep Ourbit `pending_docs_verification` with no endpoint
- [x] 12.3 Add profile scoping tests

## 13. Phase 13: operations

- [x] 13.1 Extend `docs/runbook.md`
- [x] 13.2 Add exchange counters to `common/metrics.py`
- [x] 13.3 Update `docs/architecture.md`
- [x] 13.4 Write the final run report

