## Tool discipline

Lead with Atelier’s `code_search` — one call returns the relevant symbols’ verbatim source grouped by file plus the call graph (definitions, callers, callees, usages) and a blast-radius; treat what it returns as already read. No host tool does this; prefer it over `git log` / `rg` archaeology when getting oriented in unfamiliar code. To spawn a read-only explorer or planner subagent, use the `atelier:explore` / `atelier:plan` subagent types directly rather than the built-in `Explore` / `Plan` — the Atelier ones use these indexed tools.

**Known path → always `read`.** When a file path (and optional line range) is already in hand, use `read` directly — never shell out to `sed`, `cat`, `head`, `tail`, or grep chains as a substitute. `bash` is for execution; `read` is for file content. Reaching for the shell when the path is known is always the wrong choice.

Host tools are disabled and fail with “No such tool available” — use the Atelier tool instead: `Bash` → `bash`, `Read` → `read`, `Grep` / `Glob` → `code_search`, `Edit` → `edit`.
