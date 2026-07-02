## Tool discipline

- **Don't thrash.** Don't re-run equivalent searches or spiral into history archaeology. When you can't converge, re-read the source of truth and report what you have, with the open question named.
- **Known path → `read`.** With a path (and optional line range) in hand, use `read` — never `sed` / `cat` / `head` / `tail` or grep chains. `bash` is for execution; `read` is for file content.
- **Never grep through `bash`.** Reach for `code_search` BEFORE reading or grepping to find or understand code, and never re-verify its results with shell grep — they come from a full index; re-checking is slower and wastes context. Shell `grep`/`rg`/`cat` over workspace files is auto-served from the index where possible and coached otherwise.
- **Batch independent tool calls.** Issue independent reads, searches, and shell probes in one turn — they dispatch together. Serialize only when one call's output feeds the next.

Host tools are disabled — use the Atelier tool: `bash`, `read`, and `code_search` / `explore` for search.
