# Contributing

## Development setup

Requirements: Python 3.13. Install the pinned tooling and the development
extras:

```
pip install -r requirements.txt
pip install -e ".[dev]"
```

If the test fixtures are missing, create them:

```
python scripts/create_fixtures.py
```

## Before committing

Run the default gate locally:

```
python -m pytest -m "not slow and not ml" -q
ruff check .
ruff format --check .
mypy domain
```

Pre-commit hooks run the same checks plus a gitleaks secret scan on staged
changes:

```
pre-commit install
```

## Rules

- Keep the signal pipeline ordering and the domain purity rules described in
  `AGENTS.md` and `CLAUDE.md`.
- Do not commit `.env`, `secret.salt`, `runs/`, `models/`, `config.json`, or any
  database file; `.gitignore` covers them and CI has a guard.
- Live trading stays fail-closed. Do not lower the frozen quality thresholds or
  enable live execution in a change unrelated to that work.
- Never put a real secret in code, tests, docs, or logs.

## Security

See `SECURITY.md` for reporting vulnerabilities. Do not open a public issue for
a security problem.

## License

By contributing you agree that your contributions are licensed under the
GNU General Public License v3.0 (see `LICENSE`).
