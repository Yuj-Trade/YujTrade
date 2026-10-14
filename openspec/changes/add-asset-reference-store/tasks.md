# Tasks: add-asset-reference-store

- [ ] Verify every candidate identifier against the live CoinGecko and
  Messari APIs; store unverifiable fields as `null`
- [ ] Verify `aiosqlite` is installed and pinned, or pin it before use
- [ ] Create tracked `asset_identifiers.json` (schema_version 1, one entry
  per base ticker in `symbols.txt`) plus `asset_identifiers_path` and
  `asset_reference_db_path` defaults in `ConfigManager.DEFAULT_CONFIG`
- [ ] Add frozen `AssetIdentifiers` dataclass to `common/core.py`
- [ ] Add `AssetReferenceStore` in `data/asset_reference.py` (seed load and
  validation, SQLite profile table with TTL, injected clock, idempotent
  close, never raises)
- [ ] Wire the store in `MarketDataProvider.initialize()`/`close()` and add
  the explicit `asset_reference` keyword to `BaseFetcher`,
  `MessariFetcher` and `MarketIndicesFetcher`
- [ ] Resolve CoinGecko ids and Messari slugs from the store with fallback
  to existing logic; write CoinGecko profiles after successful responses
  only for inputs containing `/`
- [ ] Add unit tests under `tests/unit/data/` per the scenarios in
  `specs/asset-reference/spec.md`, including the fetcher-compatibility
  check and the `symbols.txt` coverage check
- [ ] Run the full Phase 1 gate plus `pytest -m slow -q`; confirm golden
  hashes equal the baseline; confirm no changes under `domain/`,
  `application/`, `tests/golden/` or `symbols.txt`
