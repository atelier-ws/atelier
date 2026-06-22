# MCP Tools — Token Reduction Review

Baseline: **4 220 tokens** per turn. Per-tool:

| tool | total | desc | schema |
|------|------:|-----:|-------:|
| edit | 711 | 92 | **605** |
| grep | 446 | 45 | 387 |
| sql | 362 | 74 | 274 |
| memory | 323 | 12 | 297 |
| read | 307 | 87 | 205 |
| codemod | 290 | **187** | 83 |
| search | 269 | 44 | 210 |
| bash | 281 | 42 | 225 |
| explore | 212 | 95 | 102 |
| web_fetch | 132 | 33 | 84 |

---

## 1. `codemod` description — ~92 tok saved

| BEFORE (187 tok) | AFTER (~95 tok) |
|---|---|
| Structural code search and safe rewrite (codemod) by AST shape, via ast-grep. Matches code *shape*, not text: formatting-independent and never matches inside strings or comments. Metavariables: `$X` binds one node, `$$$` binds a list — e.g. `isinstance($X, $Y)`, `$X == None`, `requests.get($URL)`. Pass `rewrite` to transform every match; captured metavariables are reusable in the replacement, e.g. pattern `$X == None`, rewrite `$X is None`. `dry_run=True` (default) returns a unified-diff preview and writes nothing; `dry_run=False` applies the rewrite across all matched files. Scope with `language` (e.g. 'python') and `file_glob`. Returns: matches (snippet, file_path, line); with `rewrite`, a diff and `files_changed`. | AST-shape search and rewrite via ast-grep. Matches structure, not text (formatting-safe; ignores strings/comments). `$X` = one node, `$$$` = list; e.g. pattern `$X == None`, rewrite `$X is None`. `dry_run=true` (default) previews diff, false applies. Returns matches (snippet, path, line); with rewrite: diff + files_changed. |

---

## 2. `read` description — ~25 tok saved

| BEFORE (87 tok) | AFTER (~62 tok) |
|---|---|
| Read a file (or batch) with automatic source projection. Modes: outline (structure only; default for files >200 LOC), range (range='L42-L118' or open-ended 'L42-'), full (small files or expand=true), and compact. Re-read with expand=true or a range before editing against an outline/compact view. Batch 2+ files via files=[{path, range?}, ...]. | Read a file (or batch) with automatic source projection. Modes: outline (default for files >200 LOC), range (range='L42-L118' or 'L42-'), full (expand=true), compact. Batch 2+ files via files=[{path, range?}, ...]. |

---

## 3. `explore` description — ~25 tok saved

| BEFORE (95 tok) | AFTER (~70 tok) |
|---|---|
| Grouped code intelligence for a concept OR a single symbol. Concept mode (default): `query` returns grouped source + caller/callee/usage context across matched files. Targeted mode: `relation` (callers/callees/usages/self) with a `symbol` returns exactly that relation (SCIP-indexed). `depth` extends callers/callees transitively; `limit` caps targeted results; `seed_files` biases concept mode. | Code intelligence by concept or symbol. Concept mode: `query` returns grouped source + caller/callee/usage context. Targeted mode: `relation` (callers/callees/usages/self) + `symbol` returns that relation (SCIP). `depth` extends transitively; `seed_files` biases concept mode. |

---

## 4. `read` → `files` param description — ~20 tok saved

| BEFORE | AFTER |
|---|---|
| Batch read: ['path', ...] or [{path, range?, expand?, max_lines?}, ...] (strings and dicts may mix; a '#start-end'/'#line' suffix on a path scopes it). Returns {files: [...]}. Use for 2+ files — one round trip instead of N. | ['path', ...] or [{path, range?, expand?, max_lines?}, ...]. Returns {files: [...]}. Use for 2+ files. |

---

## 5. `edit` schema — strip 4 `title` keys — ~10 tok saved

Hand-written schema bypasses `_slim_schema`. These titles do nothing for the LLM.

| BEFORE | AFTER |
|---|---|
| `"title": "File edit"` | *(removed)* |
| `"title": "Notebook cell edit"` | *(removed)* |
| `"title": "Symbol edit"` | *(removed)* |
| `"title": "Projection edit"` | *(removed)* |

---

## 6. `grep` → `path` description — ~10 tok saved

| BEFORE | AFTER |
|---|---|
| Workspace-relative file or directory. A single file may carry '#start-end' (e.g. 'store.py#60-100') to scope to a line range. | Workspace path; single file may carry '#start-end' (e.g. 'store.py#60-100') to scope. |

---

## 7. `search` → `seed_files` description — ~10 tok saved

| BEFORE | AFTER |
|---|---|
| Seed files that bias ranking. Required when `mode='map'` because repo-map mode expands outward from these files. | Bias ranking; required for mode='map'. |

---

## 8. `grep` → `file_glob_patterns` anyOf — ~8 tok saved

`_slim_schema` can't auto-collapse (2 non-null branches). The null branch adds tokens but means nothing to the LLM.

| BEFORE | AFTER |
|---|---|
| `anyOf: [string, array, null]` | `anyOf: [string, array]` |

Fix: change Python annotation `str | list[str] | None` → `str | list[str]`, keep `= None` default.

---

## 9. `bash` → `background` + `session_id` descriptions — ~8 tok saved

| param | BEFORE | AFTER |
|---|---|---|
| `background` | Return a managed session handle immediately instead of blocking inline. | Return session handle immediately (non-blocking). |
| `session_id` | Session handle returned by a background run (required for action=poll/cancel). | Handle from a background run; required for poll/cancel. |

---

## Total

| # | target | savings |
|---|---|---:|
| 1 | `codemod` description | ~92 tok |
| 2 | `read` description | ~25 tok |
| 3 | `explore` description | ~25 tok |
| 4 | `read` `files` param | ~20 tok |
| 5 | `edit` schema titles | ~10 tok |
| 6 | `grep` `path` param | ~10 tok |
| 7 | `search` `seed_files` | ~10 tok |
| 8 | `grep` `file_glob_patterns` anyOf | ~8 tok |
| 9 | `bash` `background`/`session_id` | ~8 tok |
| | **Total** | **~208 tok/turn** |

---

## Parameter name renames

Param names are paid **twice**: once in the schema on every turn, and again as
JSON keys in every tool call the LLM makes. Call-time cost is the bigger one for
high-frequency tools like `grep`.

| tool.param | before | after | schema tok saved | note |
|---|---|---|---:|---|
| `grep.content_regex` | `content_regex` | `regex` | 1 | grep is called constantly |
| `grep.file_glob_patterns` | `file_glob_patterns` | `glob` | 2 | longest name in the set |
| `grep.output_mode` | `output_mode` | `mode` | 1 | matches search/sql convention |
| `grep.lines_before` | `lines_before` | `before` | 1 | |
| `grep.lines_after` | `lines_after` | `after` | 1 | |
| `grep.ignore_case` | `ignore_case` | `i` | 1 | ripgrep flag convention |
| `sql.allow_writes` | `allow_writes` | `write` | 2 | |
| `sql.connection_string` | `connection_string` | `connection` | 1 | |
| `edit.post_edit_hooks` | `post_edit_hooks` | `hooks` | 2 | |
| `web_fetch.output_format` | `output_format` | `format` | 1 | |
| `read.max_lines` | `max_lines` | `lines` | 1 | |
| `search.max_files` | `max_files` | `limit` | 1 | |
| | | **total (schema only)** | **15 tok** | |

The schema delta is modest. The call-time delta is the real win: a session with
20 grep calls each passing `content_regex` + `file_glob_patterns` costs
**20 x 3 = 60 extra tokens** just in those two keys alone.

### Compat note

Renaming a Python parameter changes the advertised JSON key, which breaks callers
passing the old name. Three options:

1. **Hard rename** — update all callers. Safe if grep on old name finds only internal uses.
2. **Alias in handler** — `args.get('regex') or args.get('content_regex')`. Keeps old callers but adds handler noise.
3. **Publish new name, accept old as hidden alias** — advertise `regex`, silently accept `content_regex` in the dispatch layer. Cleanest LLM surface without breaking tests.

Option 3 is probably right for `grep` — tests will be full of `content_regex=`.

---

## Other tools — param names

### `edit` nested properties — highest call-time impact

The edit schema is hand-written and every file edit call passes at minimum
`file_path` + `new_string`. At 30 edits/session that's a lot of key tokens.

| param | before (tok) | after | saved | frequency |
|---|---|---|---:|---|
| `file_path` | 4 | `path` (2) | **2** | every file edit |
| `new_string` | 4 | `new` (3) | 1 | every file/notebook/projection edit |
| `old_string` | 4 | `old` (3) | 1 | most file edits |
| `projected_start` | 5 | `start` (3) | 2 | projection edits |
| `projected_end` | 5 | `end` (3) | 2 | projection edits |
| `projected_ranges` | 5 | `ranges` (3) | 2 | projection edits |
| `new_body` | 4 | `body` (2) | 2 | symbol edits |
| `cell_move_target` | 5 | `target` (3) | 2 | notebook edits |
| `cell_action` | 4 | `action` (3) | 1 | notebook edits |
| `cell_type` | 4 | `type` (2) | 2 | notebook edits |
| `projection_mapping` | 4 | `mapping` (3) | 1 | projection edits |

`file_path` → `path` alone saves 2 tok × ~30 edits/session = **60 tokens/session**.
`old_string`/`new_string` → `old`/`new` adds another **60 tokens/session**.

### `codemod`

| param | before (tok) | after | saved | note |
|---|---|---|---:|---|
| `file_glob` | 4 | `glob` (2) | 2 | same name as proposed grep rename |
| `dry_run` | 4 | — | 0 | no obvious shorter form that stays clear |

### `memory`

| param | before (tok) | after | saved | note |
|---|---|---|---:|---|
| `agent_id` | 4 | `agent` (3) | 1 | `_id` suffix adds nothing here |
| `top_k` | 4 | `k` (3) | 1 | standard ML shorthand, well understood |

### Everything else — fine as-is

| tool | params checked | verdict |
|---|---|---|
| `bash` | `session_id` | marginal; `_id` convention |
| `explore` | `seed_files`, `max_files` | `seeds` saves 0 tok; `max_files` can’t be `limit` (conflict) |
| `search` | `seed_files` | saves 0 tok — skip |
| `read` | all | only `max_lines`→`lines` already flagged |
| `sql` | all | already flagged |
| `web_fetch` | all | already flagged |
| `memory` | rest | all short and load-bearing |

---

## Revised total

| category | savings/session |
|---|---:|
| Description trims (schema only) | ~208 tok |
| Param renames — schema | ~15 tok |
| Param renames — call-time (grep, 20 calls) | ~60 tok |
| Param renames — call-time (edit, 30 calls × 4 tok) | ~120 tok |
| **Total** | **~400 tok/session** |

The call-time savings from `edit` nested params + `grep` key names are larger than
all the description trims combined.
