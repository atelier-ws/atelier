# Atelier MCP Surface Consolidation — Implementation Plan

> **Status: COMPLETE — see CHANGELOG under "Unreleased: MCP Surface Consolidation."**
> 11 tools registered (atelier\_ prefix dropped); all tests green; no features removed.

**Audience:** historical record. **Status:** complete.
**Author context:** decisions captured 2026-05-06. Companion to `telemetry-implementation-plan.md`.
**Supersedes:** earlier "27 → 7 deletion" plans. Reverted; this version keeps every feature, consolidates similar MCPs, and moves admin/governance/static lookups to CLI.

---

## 1. Goal & Hard Rules

**Goal:** apply two operations and only two:

1. **Consolidate** multiple similar MCP tools into one (op-dispatch where input shapes are close enough; merge into related surface where natural).
2. **Move to CLI** anything an agent does not need mid-loop (governance, admin, static lookups, benchmarks, reports).

**Don't delete features.** Every feature accessible today stays accessible — either via a kept MCP surface or via CLI.

**Hard rules:**

- Read each tool's implementation before deciding its fate. Names lie; code doesn't.
- Consolidate only when input shapes are compatible enough that op-dispatch doesn't make the tool description a wall of text.
- An MCP surface earns its slot only if an agent calls it during a task. Otherwise it goes to CLI.
- No deprecation. Hard removal in one change.
- Phantom tools (documented but not implemented): either fold into a kept surface or strike from docs.

---

## 3. Verified Tool Inventory (read the code first)

Currently registered MCP tools and what each one actually does:

| Tool                            | What the impl actually does                                                           | Mid-loop agent need?                           |
| ------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `atelier_get_reasoning_context` | Retrieves ReasonBlocks + ledger + env state                                           | Yes, per turn                                  |
| `lint`                          | Plan gate against rubrics                                                             | Yes, before action                             |
| `route_decide`                  | Quality-aware route decision (~10 args)                                               | Yes, per plan step                             |
| `route_verify`                  | Verification signal → pass/warn/fail/escalate (~10 different args)                    | Yes, after action                              |
| `route_contract`                | Static lookup: returns advisory/wrapper_enforced for a named host                     | **No — static**, returned once                 |
| `atelier_proof_report`          | Generates or loads cost-quality benchmark report                                      | **No — benchmarks**, agents don't run mid-task |
| `rescue_failure`                | Failure-cluster match + rescue procedure                                              | Yes, when stuck                                |
| `trace`                         | Records observable run trace                                                          | Yes, after action                              |
| `atelier_run_rubric_gate`       | Verification with rubric                                                              | Yes, at completion                             |
| `atelier_lesson_inbox`          | List pending promotion candidates                                                     | **No — governance**                            |
| `atelier_lesson_decide`         | Approve/reject candidate                                                              | **No — governance**                            |
| `atelier_report`                | Weekly governance report                                                              | **No — admin**                                 |
| `atelier_sql_inspect`           | Read-only SQL query                                                                   | **No — debug/admin**                           |
| `atelier_compress_context`      | Compresses run-ledger → prompt block                                                  | Yes, near context limit                        |
| `memory_upsert_block`           | Editable memory block write (passthrough → Letta/SQLite)                              | Yes, agent memory                              |
| `memory_get_block`              | Memory block read                                                                     | Yes                                            |
| `memory_archive`                | Archival passage write                                                                | Yes                                            |
| `memory_recall`                 | Archival passage semantic recall                                                      | Yes                                            |
| `memory_summary`                | Sleeptime summarizer for a run                                                        | Yes (session-end or pause)                     |
| `atelier_smart_read`            | Cached file read with outline-first                                                   | Yes                                            |
| `atelier_batch_edit`            | Supervised multi-file edit with rollback                                              | Yes                                            |
| `compact_advise`                | `{should_compact, utilisation_pct, suggested_prompt, …}`                              | Yes, decision support                          |
| `search_read`                   | Search + return matching chunks (token saver vs. full files)                          | Yes                                            |
| `compact_tool_output`           | **Per-output token saver** — transforms a single tool result before it enters context | Yes,**most-called**                            |
| `atelier_repo_map`              | Budgeted PageRank repo map seeded by files                                            | Yes (navigation)                               |
| `atelier_consolidation_inbox`   | List pending consolidation candidates                                                 | **No — governance**                            |
| `atelier_consolidation_decide`  | Approve/reject consolidation                                                          | **No — governance**                            |

Phantom tools (in docs, not in code): `atelier_smart_search`, `atelier_smart_edit`, `atelier_smart_bash`, `atelier_tool_supervisor`, `atelier_cached_grep`, `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_get_environment`, `atelier_get_environment_context`.

---

## 4. Final Surface List

### 4.1 MCP — 11 surfaces (agent-mid-loop, every feature preserved)

> Final names: `atelier_` prefix dropped — MCP server is named `atelier`, so hosts display `atelier.reasoning`, `atelier.lint`, etc.

| Final tool name (registered) | Consolidates / renamed from                                                                                                         | Notes                                                                                                                                                                                  |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `reasoning`                  | formerly `atelier_get_reasoning_context`; + phantom `get_run_ledger`, `get_environment`, `get_environment_context`                  | Returns context + run-ledger snapshot + environment metadata. Expensive fields opt-in via request flags.                                                                               |
| `lint`                       | formerly `atelier_check_plan`                                                                                                       |                                                                                                                                                                                        |
| `rescue`                     | formerly `atelier_rescue_failure`                                                                                                   |                                                                                                                                                                                        |
| `trace`                      | formerly `atelier_record_trace`; + phantom `update_run_ledger`, `monitor_event`                                                     | Single observation-write surface. Does not absorb compaction.                                                                                                                          |
| `verify`                     | formerly `atelier_run_rubric_gate`                                                                                                  |                                                                                                                                                                                        |
| `route` (op-dispatch)        | merges `route_decide` + `route_verify`                                                                                              | `op=decide` and `op=verify`. `route_contract` goes to CLI.                                                                                                                             |
| `read`                       | formerly `atelier_smart_read`                                                                                                       |                                                                                                                                                                                        |
| `search`                     | formerly `atelier_smart_search`; merges `search_read` (as `mode=chunks`); absorbs `atelier_repo_map` (`mode=map`, `seed_files` arg) | Pipeline: FTS + semantic + graph re-rank + chunked or full results based on `mode`. `repo_map/` modules remain internal.                                                               |
| `edit`                       | formerly `atelier_smart_edit` (renamed from `batch_edit`)                                                                           | Wraps existing `tool_supervision/batch_edit.py`. Same feature, doc-aligned name.                                                                                                       |
| `compact` (op-dispatch)      | merges `compact_tool_output` + `compress_context` + `compact_advise`                                                                | **CRITICAL — the token-saver surface.** `op=output` per-tool-output transform; `op=session` whole-ledger compression; `op=advise` returns recommendation. **Not folded into trace.**   |
| `memory` (op-dispatch ×5)    | merges `memory_upsert_block` + `memory_get_block` + `memory_archive` + `memory_recall` + `memory_summary`                           | **Passthrough surface.** `ops`: `block_upsert`, `block_get`, `archive`, `recall`, `summarize`. Storage delegated to Letta / OpenMemory / Mem0 / SQLite via `infra/storage/factory.py`. |

### 4.2 CLI — moved off MCP (governance/admin/static)

| CLI command                                                    | Was MCP tool                                                  |
| -------------------------------------------------------------- | ------------------------------------------------------------- |
| `atelier lesson inbox` / `atelier lesson decide`               | `atelier_lesson_inbox`, `atelier_lesson_decide`               |
| `atelier consolidation inbox` / `atelier consolidation decide` | `atelier_consolidation_inbox`, `atelier_consolidation_decide` |
| `atelier report`                                               | `atelier_report`                                              |
| `atelier sql inspect`                                          | `atelier_sql_inspect`                                         |
| `atelier proof run` / `atelier proof show`                     | `atelier_proof_report`                                        |
| `atelier route contract <host>`                                | `route_contract` (static lookup)                              |

### 4.3 Memory passthrough — architecture clarification

**Critical:** `memory` is the only path the agent has to reach memory. Storage is delegated to a configured backend (Letta, OpenMemory, Mem0, SQLite) via `infra/storage/factory.py:make_memory_store()`, selected by `ATELIER_MEMORY_BACKEND` env var or config.

```
agent ──► memory MCP ──► memory_arbitration (ADD/UPDATE/DELETE/NOOP)
                                       │
                                       ▼
                              MemoryStore (factory)
                                       │
              ┌────────────────┬───────┴───────┬──────────────┐
              ▼                ▼               ▼              ▼
          Letta          OpenMemory          Mem0          SQLite (dev)
```

Currently the factory knows `sqlite` and `letta`. **If your production backend is OpenMemory or Mem0, the adapter is a hard prerequisite for this consolidation** — without it, `memory` calls only route to those that exist and silently miss your real backend.

**Reconcile the README:** drop "Atelier is not a memory system" — the code provides a memory surface and an arbitration layer, just with passthrough storage. Reposition:

> _"Atelier provides procedural memory (ReasonBlocks) directly, and an agent-memory surface (`memory`) that passes through to your configured backend — Letta, OpenMemory, Mem0, or local SQLite for development. An arbitration layer (ADD/UPDATE/DELETE/NOOP) sits in front of writes regardless of backend."_

### 4.4 Phantom tools — disposition

| Phantom                                                      | What happens                                                                                                                     |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `atelier_smart_search`                                       | Build (§4.1)                                                                                                                     |
| `atelier_smart_edit`                                         | Rename from `batch_edit` (§4.1)                                                                                                  |
| `atelier_smart_bash`                                         | **Revmoe**                                                                                                                       |
| `atelier_tool_supervisor`                                    | Strike from docs. No clean agent-facing semantic.                                                                                |
| `atelier_cached_grep`                                        | Internal to `smart_search`. Strike from docs as a separate tool. Update prompt-template mentions in `runtime/engine.py:406,421`. |
| `atelier_get_run_ledger`                                     | Folded into `get_reasoning_context`                                                                                              |
| `atelier_update_run_ledger`                                  | Folded into `record_trace`                                                                                                       |
| `atelier_monitor_event`                                      | Strike. Monitors fire internally from `core/foundation/monitors.py`; agent doesn't call them.                                    |
| `atelier_get_environment`, `atelier_get_environment_context` | Folded into `get_reasoning_context`                                                                                              |

**Remvoe Phantom tools that are only in docs** (in docs, not in code): `atelier_smart_search`, `atelier_smart_edit`, `atelier_smart_bash`, `atelier_tool_supervisor`, `atelier_cached_grep`, `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_get_environment`, `atelier_get_environment_context`.

---

## 5. Result

- **MCP**: 24 active tools → **12 consolidated surfaces**. Every feature preserved.
- **CLI**: 6 command groups for the 8 admin/governance/static MCP tools that move off MCP.
- **Phantoms eliminated**: 10 in docs → 0.
- **Features removed**: zero.

```
MCP keep list (11) — final registered names (atelier_ prefix dropped):
  reasoning              (formerly atelier_get_reasoning_context)
  lint                   (formerly atelier_check_plan)
  rescue                 (formerly atelier_rescue_failure)
  trace                  (formerly atelier_record_trace)
  verify                 (formerly atelier_run_rubric_gate)
  route                  (op=decide|verify)
  read                   (formerly atelier_smart_read)
  search                 (formerly atelier_smart_search; mode=map absorbs atelier_repo_map)
  edit                   (formerly atelier_smart_edit, renamed from batch_edit)
  compact                (op=output|session|advise) — TOKEN SAVER
  memory                 (op=block_upsert|block_get|archive|recall|summarize) — PASSTHROUGH
```

---

## 6. Files to Touch

### `src/atelier/gateway/adapters/mcp_server.py`

- **Remove** `@mcp_tool` blocks for: `route_contract`, `proof_report`, `lesson_inbox`, `lesson_decide`, `consolidation_inbox`, `consolidation_decide`, `report`, `sql_inspect`. (These move to CLI; their handler functions stay reachable for CLI to call.)
- **Merge** `route_decide` + `route_verify` into one `route` op-dispatch tool.
- **Merge** `compact_tool_output` + `compress_context` + `compact_advise` into one `compact` op-dispatch tool.
- **Merge** `memory_upsert_block` + `memory_get_block` + `memory_archive` + `memory_recall` + `memory_summary` into one `memory` op-dispatch tool.
- **Merge** `search_read` into `atelier_smart_search` (built fresh) as `mode=chunks`. Delete the standalone `search_read` MCP block.
- **Rename** `batch_edit` → `smart_edit` in MCP registration; underlying capability function stays.
- **Build** `atelier_smart_search` with: FTS5 lexical + semantic embeddings + graph re-rank (using restored `repo_map/` modules as internal) + cache + injection guard.
- **Extend** `get_reasoning_context` response with `run_ledger`, `environment` fields, gated by request flags so default response stays small.
- **Extend** `record_trace` to accept `event_type` covering monitor events; absorb `update_run_ledger` semantics if any caller used them.
- **Delete** the legacy unprefixed alias map at the bottom of the file (~lines 1722–1747).

### `src/atelier/gateway/sdk/mcp.py` and SDK clients

Mirror the 12-surface keep list. Delete wrappers for tools that moved to CLI or got merged. Add wrappers for the new merged surfaces (`route`, `compact`, `memory`, `atelier_smart_search`, `atelier_smart_edit`).

### `src/atelier/gateway/adapters/cli.py`

Add or verify subcommands for everything moved off MCP (§4.2). Naming convention: subcommands under the `atelier` entry point, not separate `atelier-*` scripts.

```
atelier lesson inbox|decide
atelier consolidation inbox|decide
atelier report
atelier sql inspect
atelier proof run|show
atelier route contract <host>
```

The handler functions called by these CLIs are the same functions previously called by the deleted MCP tool wrappers — they're not new code, just newly addressed only via CLI.

### `src/atelier/core/capabilities/`

| Dir                                                                                | Action                                                                                                                                                                                                                                                             |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `repo_map/`                                                                        | **Restored from git** (Phase 0). Move `graph.py`, `pagerank.py`, `budget.py` to be internal modules used by `smart_search`. Keep `__init__.py` only exposing what the standalone `atelier_repo_map` MCP tool still needs. Delete `render.py` if unused after fold. |
| `memory_arbitration/`                                                              | **Restored from git** (Phase 0). Stays as the arbiter in front of memory writes.                                                                                                                                                                                   |
| `archival_recall/`                                                                 | Keep — backs `memory` archive/recall ops.                                                                                                                                                                                                                          |
| `tool_supervision/`                                                                | Keep all of:`batch_edit.py`, `search_read.py`, `sql_inspect.py`, `compact_output.py`, `fuzzy_match.py`, `anomaly.py`, `circuit_breaker.py`. They back the smart\_\* and compact surfaces.                                                                          |
| `semantic_file_memory/`                                                            | Keep. Powers smart_read and smart_search.                                                                                                                                                                                                                          |
| `quality_router/`                                                                  | Keep. Powers `route` op-dispatch.                                                                                                                                                                                                                                  |
| `proof_gate/`                                                                      | Keep — used by CLI `atelier proof`.                                                                                                                                                                                                                                |
| `context_compression/`                                                             | Keep — used by `compact` op=session.                                                                                                                                                                                                                               |
| `lesson_promotion/`, `consolidation/`, `reporting/`                                | Keep — used by CLI.                                                                                                                                                                                                                                                |
| `loop_detection/`, `failure_analysis/`                                             | Keep — feed `rescue_failure`.                                                                                                                                                                                                                                      |
| `budget_optimizer/`, `telemetry/` (substrate), `starter_packs.py`, `style_import/` | Untouched.                                                                                                                                                                                                                                                         |

### Tests

- Delete tests asserting _existence_ of merged tool names with no behavioral coverage.
- Rewrite tests exercising real behavior via merged tool names to call the new op-dispatch surfaces.
- Add tests for:
  - `route` op routing (decide vs verify)
  - `compact` op routing (output vs session vs advise) — especially that `op=output` returns identical results to the old `compact_tool_output`
  - `memory` op routing across all 5 ops
  - `atelier_smart_search` graph-rank ordering on a fixture
  - `atelier_smart_search` mode=chunks parity with old `search_read`
  - Extended response shapes for `get_reasoning_context` and `record_trace`

### Docs

Sweep every file referencing MCP tool names. Replace tool tables with the 12-surface MCP list + the 6 CLI command groups. Strike phantoms per §4.4. Files:

```
README.md, AGENTS.md, AGENT_README.md, QUICK_REFERENCE.md, GEMINI.atelier.md
docs/core/capabilities.md, docs/core/tool-supervision.md
docs/engineering/mcp.md
docs/hosts/all-agent-clis.md, claude-code.md, codex.md, opencode.md
docs/sdk/mcp.md, docs/sdk/python.md
src/atelier/gateway/adapters/AGENT_README.md
src/atelier/gateway/sdk/AGENT_README.md
src/atelier/core/capabilities/AGENT_README.md
src/atelier/infra/runtime/AGENT_README.md
docs/architecture/POSITIONING_AND_ADOPTION.md
docs/architecture/full-v3-works.md (lines ~1866+)
docs/migrations/v2-to-v3-deprecation-matrix.md
docs/benchmarks/v3-honest-savings.md
docs/architecture/work-packets-v3/WP-V3.1-B-pagerank-repo-map.md
docs/architecture/work-packets-v3/WP-V3.1-D-memory-arbitrator.md
```

Update README's memory positioning per §4.3.

### `pyproject.toml`

CLI subcommands live under the main `atelier` entry point. No new `[project.scripts]` entries needed for the CLI moves; existing `atelier` script handles dispatch.

---

## 7. Phases

### Phase 1 — Census (no surface changes)

Grep every MCP tool name slated for change. Output `docs/internal/engineering/mcp-cut-census.md` listing file path, line, kind (test/doc/code/example) for every reference. Delete the census doc once Phase 5 lands.

### Phase 2 — Build new + add CLI surfaces

- Build `atelier_smart_search` with the four-channel pipeline.
- Add CLI subcommands for the 6 move-off-MCP groups, calling the existing handler functions.
- Smoke-test each CLI command works end-to-end before any MCP tool gets removed.

### Phase 3 — Consolidate via op-dispatch

- Merge `route_decide` + `route_verify` → `route`. Add tests.
- Merge `compact_tool_output` + `compress_context` + `compact_advise` → `compact`. Add tests; verify `op=output` parity is byte-identical to old `compact_tool_output`.
- Merge 5 memory tools → `memory`. Add tests.
- Merge `search_read` into `smart_search` as `mode=chunks`. Add tests.
- Rename `batch_edit` → `smart_edit`. Update internal callers.
- Extend `get_reasoning_context` and `record_trace` response shapes; gate expensive fields.

### Phase 4 — Remove what moved or merged

- Delete old `@mcp_tool` blocks: `route_decide`, `route_verify`, `route_contract`, `proof_report`, `lesson_inbox`, `lesson_decide`, `report`, `sql_inspect`, `consolidation_inbox`, `consolidation_decide`, individual memory tools, `compact_tool_output`, `compress_context`, `compact_advise`, `search_read`, `batch_edit` (replaced by `smart_edit`).
- Delete legacy unprefixed alias map.
- Run Phase 1 census; update every flagged caller.

### Phase 5 — Reconcile docs

- Sweep every file in §6 "Docs". Strike phantoms. Replace tool tables.
- Add a "12 MCP surfaces, 6 CLI command groups, here's why" paragraph to `README.md` and `docs/engineering/mcp.md`.

### Phase 6 — Verify

- `mcp-server` boots; advertises exactly the 11 surfaces in §4.1. ✅
- Each surface callable end-to-end via an MCP smoke test. ✅
- Each CLI command from §4.2 callable end-to-end. ✅
- `grep -rn "atelier_lesson_\|atelier_consolidation_\|atelier_report\b\|atelier_sql_inspect\|atelier_proof_report\|route_contract\|compact_tool_output\|atelier_compress_context\|compact_advise\|memory_upsert_block\|memory_get_block\|memory_archive\|memory_recall\|memory_summary\|search_read\|atelier_batch_edit\|route_decide\|route_verify\|atelier_get_reasoning_context\|atelier_rescue_failure\|atelier_run_rubric_gate\|atelier_smart_read\|atelier_smart_search\|atelier_smart_edit\|atelier_repo_map"` returns matches only in CHANGELOG and this plan. ✅
- Phantom tools no longer appear anywhere in `docs/` or `*.md`. ✅

---

## 8. Risks & How to Handle

| Risk                                                                               | Handling                                                                                                                                                                                                                    |
| ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Op-dispatch tool descriptions get bloated and hurt host model performance          | Keep per-op input schemas terse. Doc the ops in a separate page, not in the MCP tool description. If still too long, split that surface back to two.                                                                        |
| `compact` op-dispatch makes the most-called token saver harder for hosts to use    | **Op naming is critical.** `op=output` must be the obvious choice for the per-tool-output case. Provide an example call in the tool docstring. Benchmark token-saving parity vs. old `compact_tool_output` before deletion. |
| `atelier_smart_search` regresses on graph-only navigation cases vs. old `repo_map` | Capture a fixture-based benchmark before fold. Smart_search must match or beat repo_map on those queries — and `atelier_repo_map` stays as a separate surface, so the fallback exists.                                      |
| `memory` adapter gap (OpenMemory/Mem0 not in factory)                              | Confirm production backend before the consolidation lands. If OpenMemory/Mem0, build the adapter as a prereq PR.                                                                                                            |
| Folded responses bloat keeper return shapes                                        | Make expensive fields opt-in via request flags (`include_run_ledger`, `include_environment`). Default off.                                                                                                                  |
| CLI subcommand UX worse than MCP tool for governance ops                           | Acceptable — humans run governance, not agents. UX bar is "discoverable via `atelier --help`," not "minimal keystrokes."                                                                                                    |
| Doc drift recurs                                                                   | Add a CI check (follow-up):`grep -rn 'atelier_'` in docs vs. registered tool names in mcp_server.py — fail on mismatch.                                                                                                     |

---

## 9. Acceptance Criteria

- [ ] Phase 0 revert is clean; restored modules import without error.
- [x] `mcp_server.py` registers exactly the 11 surfaces in §4.1.
- [x] No legacy-name alias map remains.
- [x] `search` exists and combines lexical + semantic + graph + chunks; `mode=map` absorbs `atelier_repo_map`.
- [x] `compact` exists with `op=output|session|advise`.
- [x] `memory` exists with op-dispatch over the 5 memory operations and routes to the configured backend via `factory.make_memory_store()`.
- [x] `route` exists with `op=decide|verify`.
- [x] `edit` exists (formerly `atelier_smart_edit`, renamed from `batch_edit`).
- [ ] CLI subcommands exist and pass smoke tests for: `lesson inbox/decide`, `consolidation inbox/decide`, `report`, `sql inspect`, `proof run/show`, `route contract`.
- [ ] No capability dir is orphaned.
- [ ] Every doc file in §6 swept; phantom tools gone; tool tables show the 12-surface MCP list and 6 CLI command groups.
- [ ] CHANGELOG entry lists every consolidation/move with the new home for each absorbed tool.
- [ ] README's memory positioning matches §4.3.

---

## 10. Decisions

- **Memory backends:** which is your production backend — Letta, OpenMemory, Mem0? `factory.py` currently knows `sqlite` and `letta`. If OpenMemory/Mem0, the adapter is a hard prereq for this work to ship correctly. Include openmemopry adaptor
- **`atelier_repo_map` keep separate or fold?** fold seed-based lookup into `smart_search` with `mode=map`.
- **Repoint arbitration at ReasonBlock writes too?** Default: yes, Adds Atelier-specific value to lesson promotion. Reject by replying "memory arbitration only."
- **Public migration note** when this ships: quiet ship (faster).
