Project Skills
Skill Discovery and Usage

The project-level skills are located in the skills/ directory at the repository root.

Before performing any task:

Treat <project-root>/skills/ as the canonical source of project skills.
Inspect the skills/ directory and identify skills relevant to the current task.
Read the complete SKILL.md file of every relevant skill before executing the task.
If a skill contains supporting files such as references/, scripts/, examples/, or other referenced resources, read them when the SKILL.md instructs you to do so or when they are required to correctly perform the task.
Apply all relevant skill instructions throughout the task.
If multiple skills are relevant, load all of them and resolve their instructions together before making changes.
Do not ignore a relevant project skill because another agent, tool, or framework has its own skill/rules directory.
Do not modify, rename, move, or delete files under skills/ unless the user explicitly requests a change to the skills themselves.
If no relevant skill exists, proceed using the instructions in this AGENTS.md and the rest of the project's documentation.
Never assume the contents of a skill. Read the actual SKILL.md before relying on it.
Skill Priority

When a project skill applies to the current task, its instructions are mandatory.

Use this precedence when instructions conflict:

System instructions
User instructions
AGENTS.md
Relevant project skills under skills/
Other project documentation
Agent/tool defaults
Required Workflow

For every task:

1. Identify the project root.
2. Inspect skills/.
3. Determine which skills are relevant.
4. Read the relevant SKILL.md files completely.
5. Read required supporting resources referenced by those skills.
6. Apply the skill instructions.
7. Perform the requested task.
8. Verify the result against the applicable skills and project rules.

The skills/ directory at the project root is the authoritative project-level skill source.

## Repository-specific operating guide

### Scope and source of truth

- The repository root is `C:\ME\YujTrade`. `Main/` is a vendored Python
  environment, not application code. Never edit it or include it in searches.
- Read `CLAUDE.md` for the complete architecture and domain contracts. Read
  `README.md` and the relevant file under `docs/` before changing behavior.
- `openspec/AGENTS.md` is an additional mandatory guide for requests involving
  proposals, planned capabilities, breaking changes, or architecture work.
- Do not modify files under `skills/`, `Main/`, generated runtime directories,
  or secret/config files unless the request explicitly includes them.

### Architecture boundaries

- `domain/` is the pure decision core and may import only the standard
  library. `application/` may depend on `domain` and the standard library.
  Higher-level packages must not move business decisions into entrypoints.
- `services/trading_service.py:create_trading_stack()` is the sole composition
  root. Reuse its returned `(config_manager, resource_manager,
  market_data_provider, trading_service)` tuple and preserve caller-owned
  cleanup.
- Keep the signal pipeline ordered as
  `SignalGenerator` -> `MultiTimeframeAnalyzer` -> quality gates ->
  `SignalRanking`. Use `application/gate_config.py:build_gate_config()` for
  both generator and service.
- Keep live and historical behavior aligned: backtests resolve outcomes through
  `domain/outcome.py`, and holdout paths remain causal and isolated from live
  external/ML data unless the documented opt-in checks pass.

### Change and validation workflow

1. Inspect the target package, its tests, and related ADRs before editing.
2. Preserve Python 3.13 compatibility, async I/O boundaries, absolute imports,
   loguru logging, and the repository's no-comments production-code rule.
3. Never hardcode secrets, model data limits, gate thresholds, or runtime
   overrides. Use `ConfigManager`, `SecretsManager`, and existing helpers.
4. Run the smallest relevant test first, then the default gate when behavior
   changes:

   ```text
   python -m pytest -m "not slow and not ml" -q
   ruff check .
   ruff format --check .
   mypy domain
   ```

5. For model, backtest, or signal changes, also preserve golden JSON hashes and
   run the applicable slow/golden checks. Never use logs as a replacement for
   tests.
6. Before committing, check `git diff --check`, `git status --short`, and
   confirm that only requested files are staged.

### Safety and repository hygiene

- `.env`, encryption material, databases, model binaries, calibration/history
  files, `runs/`, `artifacts/`, and `models/` are runtime or secret data and
  must never be committed.
- Paper execution is the default. Do not enable live execution or lower
  frozen quality thresholds as part of an unrelated change.
- Missing Telegram credentials must result in the documented startup failure
  after cleanup; do not make the application silently idle.
- Use focused edits and preserve unrelated work already present in the
  working tree. Do not reset, discard, or amend commits without explicit
  authorization.
