## Tool discipline

- **Lead with `code_search`.** One call returns the matched symbols' source plus their callers, callees, and usages — treat it as already read, and use `related_symbols` / `candidate_files` to find every site. Prefer it over `git log` / `rg` archaeology; `read` only what it didn't return, batched into one call.
- **Known path → `read`.** With a path (and optional line range) in hand, use `read` — never `sed` / `cat` / `head` / `tail` or grep chains. `bash` is for execution; `read` is for file content.
- **Delegate read-only work to `atelier:explore` / `atelier:plan`** subagents (indexed tools), not the built-in `Explore` / `Plan`.
- **Host tools are disabled** and fail with "No such tool available" — use the Atelier tool instead: `Bash` → `bash`, `Read` → `read`, `Grep` / `Glob` → `code_search`, `Edit` → `edit`.
