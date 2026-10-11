# Open Issues Register

Migration v2.0 — residual and out-of-scope items. Updated as phases complete.
A `blocked` entry never guesses missing content; it records the reason and moves on.

## Blocked

- [ ] `trading/` live execution internals beyond the paper ledger: no live-exchange
  adapter exists in the repo. Live trading stays out of scope; paper only.
- [ ] `bulk_download` for higher timeframes (network access): needs user approval
  and execution. Until then `mtf_data_missing` rejections are expected on thin data.
- [ ] Production holdout/train with real data: user-run via `docs/runbook.md`
  after the migration. Agent never runs network training.
- [ ] `LONG_TERM_CONFIG` thresholds and indicator formulas: frozen by directive
  (only causality fixes allowed in phase 4). No change recorded.

## Pre-flight audit (directive v3.0, phase A — verified locally)

- [x] `ci.yml` **exists** (`.github/workflows/ci.yml`): jobs `ruff check .`
  (full-repo), `mypy domain`, `pytest -m "not slow and not ml"`. The v2.0
  audit claim "CI absent" is stale. CI is currently RED because of the ruff
  debt below; phase D must turn it green.
- [x] Ruff baseline: **948 errors** (641 auto-fixable). Top rules: `UP006`
  244, `E501` 198, `UP045` 185, `F401` 111, `UP035` 95, `I001` 71.
- [x] Pytest baseline: **142 passed, 2 deselected** (`-m "not slow and not ml"`).
- [x] Tracked binaries: 27 `.pkl` files under `models/lstm|models/xgboost`.
  `calibration.json` is **not** tracked (the note in "Legacy tracked
  artifacts" below is stale and will be corrected in phase G). No
  default-marker test reads legacy `models/`; `ModelManager` predict path
  goes through `ArtifactRegistry` (`artifacts/`). Untrack approved (phase B).
- [x] Junk scripts `fix_test.py`, `tests/_fix_p1.py`, `tests/_probe_p1.py`,
  `prompt` have no importers outside themselves. Removal approved (phase B).
  Residual strays kept for now: `^` (0 bytes), `symtemp.txt`, `symbols.txt`
  (no `.py` references found).
- [x] Fixtures are exactly 1501 lines each (header + 1500 rows) but synthetic
  per the v2.0 report; `signals_baseline.json` is `[]`. No warehouse DB on
  disk and `config.json` carries no warehouse path → phase F is **blocked**
  until the user supplies real warehouse data.
- [x] Docs are stubs: ADRs 189–258 bytes, README 41 lines, runbook 27 lines;
  `CLAUDE.md` claims "no test suite" (stale). Phase G required.
- [x] Test gaps confirmed: `tests/unit/backtesting/` has only
  `test_simulator.py` (no walk-forward/holdout tests); `tests/unit/modeling/`
  has only `test_predict_no_autotrain.py`. Phase E required.
- [x] Local `.gitignore` noise (duplicate `/copyfile` + `copyfile/copy.py`
  lines) reverted to HEAD; the exporter script stays tracked.

## Legacy tracked artifacts (do NOT delete without backup + migration)

The denylist in `.gitignore` covers `.env`, `secret.salt`, `*.keras`, `*.pkl`,
`*.db`, `calibration.json`, `signal_history.json`. These paths are already
tracked from earlier history and must stay untouched until a dedicated,
backed-up removal is approved:

- `models/lstm/*.pkl` (tracked scalers)
- `calibration.json` (tracked at repo root)
- any `*.db` under `runs/` created at runtime (untracked, ignored)

## Out of scope (user-side, section 6 of the directive)

- [ ] Move `ENCRYPTION_PASSWORD` to `SECRET_ENCRYPTION_PASSWORD` env var (user).
- [ ] Physical reshuffle into `infrastructure/` (future work).
- [ ] Organization secret manager adoption (future work).
- [ ] Live execution enablement (future work, requires `execution_dry_run` review).

## Resolved

- [x] S.3 `.gitignore` denylist: already complete, no commit needed.
- [x] S.5 snapshot: working tree was clean on `main`, no snapshot commit needed.
- [x] Phase 2.5 `hash_data` versioning: `hash_data`/`verify_hashed_data` have no
  callers outside `utils/security.py`; format stays `<salt>$<hash>` at 480000
  iterations, no `v2$` migration required.
- [x] Phase 2.6 warehouse filename: no `data warehouse.db` reference remains.
- [x] Phase 9 `calculate_overall_quality_score`: kept as-is. The provider path
  now uses the newer quality helpers; the orphan stays covered by existing
  tests and is not called in production flow. No silent removal performed.
- [x] Phase 10 README Backtest section: corrected to real entry points
  (`EventDrivenSimulator`, `WalkForwardValidator.split`,
  `scripts/run_holdout.py`); stale `run_walk_forward`/`walk_forward_splits`
  names removed.

## Known debt (non-blocking)

- Full-repo `ruff check .` reports ~970 pre-existing violations (mostly
  `E501`, `UP035`, `E402` in legacy code). Per-commit gate stays scoped
  (`ruff check` on touched paths plus `domain`/`tests` additions,
  `mypy domain`, full default-marker pytest). Cleanup tracked here, not
  attempted as drive-by reformatting during the migration.
