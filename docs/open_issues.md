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
