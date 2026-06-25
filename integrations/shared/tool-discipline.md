## Tool discipline

Lead with Atelier's code-intel tools — `explore` (call graph: definitions, callers, callees, and usages in one call) and `search` (semantic code search). No host tool does this; prefer them over `git log` / `rg` archaeology when getting oriented in unfamiliar code. To spawn a read-only explorer or planner subagent, use the `atelier:explore` / `atelier:plan` subagent types directly rather than the built-in `Explore` / `Plan` — the Atelier ones use these indexed tools.

Host tools are disabled and fail with "No such tool available" — use the Atelier tool instead: `Bash` → `bash`, `Read` → `read`, `Grep` / `Glob` → `explore`, `Edit` → `edit`.
