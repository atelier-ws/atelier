## Tool discipline

- **One search → one bulk edit.** Lead with `code_search` — treat its source as already read, use `related_symbols` / `candidate_files` to find every site. `read` only what it didn't return, all files in ONE call, never the same file twice. Make ALL edits in ONE `edit` `edits[]` array. The read→edit→read→edit loop is the main cost.
- **Don't thrash.** Don't re-run equivalent searches or spiral into history archaeology. When you can't converge: re-read the code under change and what defines its expected behavior (test, caller, spec), name the root cause in one line, then edit.
- **Known path → `read`.** With a path (and optional line range) in hand, use `read` — never `sed` / `cat` / `head` / `tail` or grep chains. `bash` is for execution; `read` is for file content.
- **Delegate read-only work to `atelier:explore` / `atelier:plan`** subagents (indexed tools), not the built-in `Explore` / `Plan`.

Host tools are disabled — use the Atelier tool: `bash`, `read`, `edit`, and `code_search` / `explore` for search.
