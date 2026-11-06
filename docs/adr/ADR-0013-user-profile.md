# ADR-0013: User profile (Telegram-managed settings and keys)

Status: proposed

Approved by owner via implementation brief, 2026-11-06.

## Context

The operator wants to manage exchange API keys, data-provider keys and the
personalizable trading settings from Telegram, without editing
`config.json`/`.env` on the host. Defaults must reproduce today's behavior
exactly, so every profile value is an override: when nothing is stored, the
frozen `ConfigManager.DEFAULT_CONFIG` and `LONG_TERM_CONFIG` values apply.

## Decision

### 1. The profile is an override layer, never a new source of truth

`ConfigManager.DEFAULT_CONFIG` stays the single source of defaults
(repository rule). The profile schema (`config/profile_schema.py`) declares
type, range and choices only, the encrypted store lives in
`config/profile_keys.py`, and the apply helpers live in
`app/profile_service.py` (`application/` may import only `domain` and the
standard library, so the store cannot live there), and the menu lives in
`app/telegram_profile.py`. A test asserts schema defaults equal
`DEFAULT_CONFIG` values. `LONG_TERM_CONFIG` constants are not edited; keys
that currently read `LONG_TERM_CONFIG` (analysis timeframes, per-timeframe
confidence, `min_risk_reward_ratio` gate, `max_signals_per_run`) read the
profile override first and fall back to the constant.

### 2. Operator-only exclusions

The profile cannot change: `exchange_enabled`,
`exchange_access_profile`, `exchange_sandbox`, `exchange_shadow_mode`,
`execution_dry_run`, `exchange_live_enabled`, `exchange_live_review_id`,
`exchange_symbol_allowlist`, halt controls, the safety caps
(`exchange_max_order_notional_usdt`, `exchange_max_daily_notional_usdt`,
`exchange_max_price_deviation_pct`, `exchange_max_spread_pct`),
`exchange_attested_keys`, infrastructure keys (Telegram/admin/Redis/DSN
secrets, every `*_path`/`*_db_path`, `METRICS_PORT`, `metrics_enabled`,
cache TTLs, rate limits, exchange timeouts and reconciliation intervals,
`indicator_weights.json`), data integrity (`min_data_points`,
`model_data_limits`, `model_prediction_limit`), modeling keys
(`model_learning.*`, `drift_*`, `promotion_*`, `feature_store_*`,
`prediction_trace_*`, `ohlcv_store_*`, `model_auto_train_on_predict`), and
the legacy `paper_fee_rate` / `paper_slippage_rate`. Access controls stay out
of Telegram reach per ADR-0012 section 3: no Telegram command changes the
access profile or widens reachability.

### 3. Secret storage: one Fernet token per value in `runs/profile_keys.enc.json`

Each secret is encrypted separately with `KeyEncryptor`
(`utils/security.py`) and the file is written atomically (temp file +
`os.replace`), with 600-equivalent permissions where the OS supports them
(Windows uses the user profile directory ACL; the explicit chmod is applied
when `os.chmod` accepts it). Structure:

```json
{"exchanges": {"<exchange_id>": {"sandbox": {"api_key": "...", "api_secret": "..."}},
               "providers": {"CRYPTOPANIC_KEY": "..."}}
```

`runs/` is already gitignored. If no encryptor is available
(`SECRET_ENCRYPTION_PASSWORD` missing) saving is refused with an explicit
message; nothing is written. Values are never echoed to chat, never logged,
and never enter `config.json`.

Lookup order: profile store first, then the existing
`.env` `ENCRYPTED_<NAME>` path. The plaintext rule of
`credentials_usable` (plaintext in `.env` disables credentials) is unchanged.

### 4. Provider keys: rebuild the affected fetchers after a save

`SecretsManager` snapshots provider keys as class attributes at import time
and `MarketDataProvider.initialize()` bakes them into fetcher constructors.
Reading the profile at call time would require touching every fetcher, so
the chosen mechanism is a targeted rebuild: after a provider key is saved,
`MarketDataProvider.rebuild_keyed_fetchers()` reconstructs the coindesk,
coingecko, alphavantage, messari and news fetchers from
profile-store-first lookups. This keeps fetcher code untouched and avoids
import-time mutation of `SecretsManager`.

### 5. Attestation is removal-only, and enforced against the running service

Saving or deleting any key of a venue removes that venue from
`exchange_attested_keys` in `config.json` and, when a live exchange service
exists, replaces its frozen `ExchangeSettings` (via `dataclasses.replace`)
and clears that venue's cached permission verdict and reconciliation state.
No code path adds a venue to the attested list. Most venues expose no
permission endpoint (`permission_endpoint is None` for all but Binance and
LBank), so attestation is the only guard for them — a known gap recorded in
`docs/open_issues.md`.

### 6. Gateways: no persistent cache to drop

Gateways are built per submission/reconciliation pass and closed after use
(`trading/exchanges/execution_service.py`); there is no long-lived gateway
object to invalidate. Key rotation therefore takes effect by (a) the profile
being consulted first in `load_exchange_credentials`, and (b) clearing the
venue's permission-cache entry and `reconciled_venues` membership so the
next submission rebuilds the gate with the new key. A restart also works.

### 7. In-place risk updates

`RiskManager.config` `RiskConfig` fields are updated in place on save
because `PaperTradingEngine` holds the `RiskManager` by reference
(`create_trading_stacks` wires one `RiskManager` into both the service and
the paper engine). The `RiskManager` object is never replaced.

## Consequences

- Golden files stay byte-identical: with no overrides stored, every consumer
  reads the same literals as before.
- `initial_cash`, the paper cost engine's cached profile, notification
  policy, scheduler interval and provider settings that are read at startup
  are reported as "applies after restart".
- Secrets have a second at-rest location; its encryption strength equals the
  existing `.env` scheme (same password, same salt file).
