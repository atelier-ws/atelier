# atelier-codex — Codex skill pack

Skill-only packaging of the Atelier reasoning loop for OpenAI Codex (and
Codex-compatible CLIs that read SKILL.md frontmatter).

## Layout

```
atelier-codex/
├── mcp.json                        # Codex MCP server registration
├── references/workflow.md          # canonical reasoning loop
└── skills/
    ├── atelier-task/SKILL.md
    ├── atelier-check-plan/SKILL.md
    ├── atelier-rescue/SKILL.md
    └── atelier-record-trace/SKILL.md
```

## Install

1. Install the engine:
   ```bash
   cd atelier && uv sync
   uv run atelier init   # creates .atelier/ at workspace root
   ```
2. Make `atelier-mcp` available on `$PATH`, or set
   `ATELIER_VENV` to the venv that holds it.
3. Point Codex at this directory's `mcp.json` (or merge it into your
   Codex MCP config). The substitution `${workspaceRoot}` is what Codex
   uses; if your Codex client uses a different placeholder, adapt.
4. Tell Codex to load skills from `atelier-codex/skills/`. (Codex skill
   discovery varies by client — see your client docs.)

## Usage

Once skills are loaded, Codex auto-triggers `atelier-task` on every
coding prompt. The skill instructs Codex to call the Atelier MCP tools
in order. See [references/workflow.md](references/workflow.md) for the
authoritative procedure.

## Hard rules

- Never edit before `atelier_check_plan` returns `ok`.
- Never retry a failing command a third time without
  `atelier_rescue_failure`.
- Never declare success on high-risk domains without
  `atelier_run_rubric_gate`.
- Never record secrets or hidden chain-of-thought.
