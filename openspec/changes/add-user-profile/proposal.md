# Add User Profile (Telegram-managed settings and keys)

## Why

The operator can currently change settings only by editing `config.json` or
`.env` on the host and restarting. Owner asked for a Telegram "Profile" menu
that manages exchange API keys, data-provider keys, and every personalizable
trading setting, with defaults that reproduce today's behavior exactly.

Approved by owner via implementation brief, 2026-11-06.

## What Changes

- Add a profile schema (`config/profile_schema.py`) covering sections
  4.3–4.9 of the brief; the schema holds type, range and choices only, while
  `ConfigManager.DEFAULT_CONFIG` stays the single source of defaults.
- Add new `DEFAULT_CONFIG` keys for previously hard-coded values: stop/target
  ATR and min-RR parameters, loss-streak sizing parameters, analysis
  timeframe lists, per-timeframe confidence map, and the signal-gate RR ratio.
- Add an encrypted key store (`runs/profile_keys.enc.json`) for exchange API
  keys and data-provider keys; lookup order is profile store first, then the
  existing `.env` encrypted path.
- Add a Telegram Profile menu (`/start` third row, callback prefix `pf:`)
  with submenus for exchange keys, service keys, risk, stop and target,
  analysis, notifications and schedule, paper and costs, reporting, and reset.
- Apply changes without restart wherever the code reads values at call time
  (risk config, gates, analysis timeframes, cost model); everything cached at
  startup is reported as "applies after restart".
- Operator-only settings stay out of reach of the menu (exchange access,
  safety caps, attestation, infrastructure, data integrity, modeling).
- Saving or deleting a venue key removes that venue from
  `exchange_attested_keys`; nothing in the profile ever adds a venue back.

**BREAKING**: none. Defaults are byte-identical to current behavior; golden
files are unchanged.

## Impact

- Affected specs: `user-profile` (new capability)
- Affected code: `config/profile_schema.py` (new), `config/profile_keys.py`
  (new: encrypted store), `app/profile_service.py` (new: apply helpers),
  `app/telegram_bot.py` (+ `app/telegram_profile.py`, new menu),
  `trading/risk_manager.py`, `strategy/signal_generator.py`,
  `services/trading_service.py`, `common/utils.py`
  (`calculate_dynamic_levels` gained optional parameters),
  `data/data_provider.py` (provider key rebuild), `config/settings.py`
  (`DEFAULT_CONFIG` additions), `main.py` (handler wiring).
- Docs: `docs/adr/ADR-0013-user-profile.md`, `docs/runbook.md`,
  `docs/open_issues.md`, `README.md`.
- Operator-only exclusions are documented in ADR-0013-User-Profile; access
  controls stay frozen per `docs/adr/ADR-0012-exchange-governance.md`
  section 3.
