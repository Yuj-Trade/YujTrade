## 1. Phase 1: baseline and existing bug fixes

- [ ] 1.1 Record the baseline gate result and the golden hashes
- [ ] 1.2 Pin `ccxt` to an exact version in `requirements.txt`
- [ ] 1.3 Make `ExchangeAdapter` fail closed in the non dry-run path
- [ ] 1.4 Add `tests/unit/trading/test_exchange_adapter_fail_closed.py`

## 2. Phase 2: pure domain, ports, policy and registry

- [ ] 2.1 Add `domain/exchange_types.py`
- [ ] 2.2 Add `application/exchange_ports.py`
- [ ] 2.3 Add `application/exchange_policy.py`
- [ ] 2.4 Add `trading/exchanges/registry.py` with the 22 venues
- [ ] 2.5 Add domain, policy, registry and no-withdraw tests

## 3. Phase 3: encrypted exchange secrets

- [ ] 3.1 Add `SecretsManager.get_exchange_secret` with no plaintext fallback
- [ ] 3.2 Add `trading/exchanges/credentials.py`
- [ ] 3.3 Merge registry secret names into `scripts/encrypt_keys.py`
- [ ] 3.4 Extend the log redaction pattern
- [ ] 3.5 Add `trading/exchanges/errors.py` with `sanitize`
- [ ] 3.6 Add credential tests including a log-leak test

## 4. Phase 4: read-only market data gateway

- [ ] 4.1 Add `trading/exchanges/ccxt_gateway.py` (public methods)
- [ ] 4.2 Add `trading/exchanges/factory.py`
- [ ] 4.3 Add `scripts/probe_exchanges.py`
- [ ] 4.4 Add offline gateway tests with a fake client

## 5. Phase 5: authenticated reads and key permission check

- [ ] 5.1 Add `fetch_free_balance` and `fetch_order_by_client_id`
- [ ] 5.2 Add `verify_key_permissions`
- [ ] 5.3 Add permission-check tests with fixtures

## 6. Phase 6: live ledger and reconciliation

- [ ] 6.1 Add `trading/live_ledger.py`
- [ ] 6.2 Add `trading/reconciliation.py`
- [ ] 6.3 Add ledger, restart and unknown-status tests

## 7. Phase 7: sandbox order submission

- [ ] 7.1 Add `trading/exchanges/gate_inputs.py`
- [ ] 7.2 Add `trading/exchanges/execution_service.py`
- [ ] 7.3 Implement `place_limit_order` in the gateway
- [ ] 7.4 Add the exchange keys to `ConfigManager.DEFAULT_CONFIG`
- [ ] 7.5 Wire the service in `create_trading_stack` and `TradingService`
- [ ] 7.6 Add submission tests with a fake gateway

## 8. Phase 8: administrator Telegram controls

- [ ] 8.1 Add `/exchanges` and `/exchange_status`
- [ ] 8.2 Add `/exchange_execute`, `/exchange_halt` and `/exchange_resume`
- [ ] 8.3 Add non-admin and no-secret-leak tests

## 9. Phase 9: shadow mode

- [ ] 9.1 Keep shadow mode free of any `place_limit_order` call
- [ ] 9.2 Add `scripts/exchange_shadow_report.py`
- [ ] 9.3 Add the shadow test with a call counter

## 10. Phase 10: live activation mechanism

- [ ] 10.1 Add the one-time confirmation code flow
- [ ] 10.2 Add the activation checklist to `docs/runbook.md`
- [ ] 10.3 Add gate tests covering every incomplete condition
- [ ] 10.4 Record the operator-only steps in `docs/operator_pending.md`

## 11. Phase 11: further general venues

- [ ] 11.1 Document the probe procedure and results table
- [ ] 11.2 Isolate per-venue quirks inside `ccxt_gateway.py`

## 12. Phase 12: Iran access profile

- [ ] 12.1 Correct the LBank `ccxt_id` to the verified v2 class
- [ ] 12.2 Keep Ourbit `pending_docs_verification` with no endpoint
- [ ] 12.3 Add profile scoping tests

## 13. Phase 13: operations

- [ ] 13.1 Extend `docs/runbook.md`
- [ ] 13.2 Add exchange counters to `common/metrics.py`
- [ ] 13.3 Update `docs/architecture.md`
- [ ] 13.4 Write the final run report
