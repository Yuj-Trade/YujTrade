# add-user-profile Tasks

## 1. Schema and defaults

- [ ] 1.1 `config/profile_schema.py` with per-key type, range/choices, section and restart flag
- [ ] 1.2 New `DEFAULT_CONFIG` keys (defaults equal to current behavior)
- [ ] 1.3 Schema/default parity test, validation tests, excluded-key rejection test

## 2. Stop and target parameters

- [ ] 2.1 `calculate_dynamic_levels` optional parameters from profile, defaults unchanged
- [ ] 2.2 Regression grid (ADX 35, 35.0001, 40, 40.0001; structure flags on/off)

## 3. Risk, analysis and cost parameters

- [ ] 3.1 `build_risk_config` reads the new loss-streak keys; `size_multiplier` uses them
- [ ] 3.2 In-place `RiskManager.config` updates after a profile save
- [ ] 3.3 Analysis timeframes, quick timeframe, gate overrides read profile at call time
- [ ] 3.4 Signal gate `signal_min_risk_reward_ratio` override
- [ ] 3.5 Paper cost model validation via `cost_profile_from_config`, engine profile update

## 4. Encrypted key store

- [ ] 4.1 `application/profile.py` store: encrypt each value, atomic write, 600 permissions
- [ ] 4.2 Exchange credential lookup: profile store first, then `.env` path
- [ ] 4.3 Provider key lookup: profile store first, then `SecretsManager`; rebuild fetchers after save
- [ ] 4.4 Attestation reset on save or delete; no add path
- [ ] 4.5 Refuse to save when no encryptor is available

## 5. Telegram menu

- [ ] 5.1 `/start` Profile button, submenus, per-parameter render, reset
- [ ] 5.2 Pending text input with 120 s expiry, Cancel, validation feedback
- [ ] 5.3 Key flow: venue paging, environment, field, delete-message, delete key
- [ ] 5.4 Non-admin guards; no-secret-in-chat/log guarantees

## 6. Docs

- [ ] 6.1 ADR-0013 proposed
- [ ] 6.2 Runbook profile section; README paragraph; open issues
