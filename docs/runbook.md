# Operations runbook

1. Copy `.env.example` to `.env` and set `SECRET_ENCRYPTION_PASSWORD`.
2. Run `python -m pytest -m "not slow and not ml"` before deployment.
3. Train models explicitly with `python scripts/train_models.py`.
4. Run the bot with `python main.py`; paper execution remains the default.
5. Use `/signals` for reporting and `/paper` for an explicit paper order.
6. Keep `execution_dry_run=True` until a separately reviewed live deployment.
