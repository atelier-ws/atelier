## Tool discipline

- **One search → one bulk edit.** Lead with `code_search` — treat its source as already read, use `related_symbols` / `candidate_files` to find every site. `read` only what it didn't return, all files in ONE call, never the same file twice. Make ALL edits in ONE `edit` `edits[]` array. The read→edit→read→edit loop is the main cost.
- **Don't thrash.** No history archaeology; when you can't converge, re-read the code under change and what defines its expected behavior (test, caller, spec), name the root cause in one line, then edit.
- **Known path → `read`.** Never `sed` / `cat` / `head` / `tail` or grep chains — `bash` is for execution; `read` is for file content.
- **Never grep through `bash`.** Never re-verify `code_search` results with shell grep — they come from a full index. Shell `grep`/`rg`/`cat` over workspace files is auto-served from the index where possible and coached otherwise.
- **Batch independent tool calls.** Issue independent reads, searches, and shell probes in one turn — they dispatch together. Serialize only when one call's output feeds the next.
- **Large output → a file, never prose.** Write it with the file tools or a small generator script (`… > out`), not inline in a reply.
- **Delegate read-only work to `atelier:explore` / `atelier:plan`** subagents (indexed tools).

Host tools are disabled — use the Atelier tool: `bash`, `read`, `edit`, and `code_search` / `explore` for search.
