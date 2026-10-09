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
