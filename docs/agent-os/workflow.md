# Agent OS Workflow

Use this default loop for coding work in Atelier:

1. **Understand** - read the relevant source of truth first; ground every change in real code.
2. **Plan** - keep the plan small, concrete, and grounded in the relevant files.
3. **Implement** - make the change with Atelier MCP tools for file I/O, search,
   edits, and shell work whenever they are available. Native host tools are
   fallback only when Atelier returns `noop`, is hidden, or is unavailable.
   Update directly related docs when the rule surface changes.
4. **Recover** - if the same approach fails twice, change strategy. Do not retry a third time.
5. **Verify** - before concluding, for code changes always run formatting, linting,
   type checks, and relevant tests from [validation-matrix.md](validation-matrix.md).
   See [review-rubric.md](review-rubric.md) for the full adversarial discipline.

## Delegation (cheaper-model subagents)

For expensive or self-contained subtasks (write tests, refactor a module, generate docs,
run a long search), delegate to a cheaper-model sub-agent instead of doing it inline:

1. Spawn read-only or self-contained work on a cheap model tier with your native spawn tool:
   - **Claude Code**: `Agent(agent_type="general-purpose", model="haiku", prompt=...)`
   - **Copilot CLI**: `task(agent_type="general-purpose", prompt=...)`
   - **Codex / OpenCode**: `Task(prompt=..., model=...)`
2. Keep edit/implement work that needs the current model inline.
3. The subagent bootstraps its own Atelier context automatically via the prompt prefix.

## Budget guardrails

- Name the deliverable before editing.
- Summarize the smallest viable plan.
- Keep context narrow: current goal, relevant files, failing command or output,
  and known constraints.
- Restate working context in under 10 bullets before editing or after compaction.
- If more than 10 minutes pass without an edit, restate the expected deliverable.

## Symbol-first navigation

When the symbol name is known, use the code-intel tools — not text search:

1. **Known symbol name** → `symbols` then `node` (name-first lookup). Never raw grep.
2. **"Find X and everything that calls/uses it"** → `symbols`/`node` then `usages`.
3. **Who calls a function** → `callers` instead of reading the file and tracing manually.
4. **Understand a concept across files** → `explore` (grouped source + relationships).
5. **Refactors targeting a named symbol** → `edit kind="symbol"`. Not raw `edit` with line numbers.

## Documentation loop

Update live docs when you change:

- repository-wide rules
- architecture boundaries
- validation commands
- plan and decision workflows
- host instruction generation
