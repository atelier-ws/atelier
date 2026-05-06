# Atelier MCP Tool Surface Cut — Implementation Plan

**Audience:** coding agent picking up the cut. **Status:** approved, ready to execute.
**Author context:** decisions captured 2026-05-06. Companion to `telemetry-implementation-plan.md`.

---

## 1. Goal

Reduce the MCP tool surface from ~27 registered tools to **7 keepers**, by deleting outright (no deprecation cycle, no shims, no aliases) and folding/merging where the value belongs in another tool.

**Why:** every MCP tool is a documentation cost the host model pays on every call, an API surface to maintain, and a chance for the agent to pick the wrong tool. The current surface contradicts the README's stated identity ("Atelier is not a memory system" while shipping 5 memory tools) and includes governance/reporting tools that humans should run via CLI, not agents mid-loop.

**Hard rule:** delete, don't deprecate. No `deprecated_in` fields. No legacy-name aliases. No "ship as no-op for one release." Cut means cut.

---

## 2. Ground Truth — what's actually in the code right now

`src/atelier/gateway/adapters/mcp_server.py` currently registers these `@mcp_tool` names (verified 2026-05-06):

```
atelier_get_reasoning_context     atelier_check_plan
atelier_route_decide              atelier_route_verify
atelier_route_contract            atelier_proof_report
atelier_rescue_failure            atelier_record_trace
atelier_run_rubric_gate           atelier_lesson_inbox
atelier_lesson_decide             atelier_report
atelier_sql_inspect               atelier_compress_context
atelier_memory_upsert_block       atelier_memory_get_block
atelier_memory_archive            atelier_memory_recall
atelier_memory_summary            atelier_smart_read
atelier_batch_edit                atelier_compact_advise
atelier_search_read               atelier_compact_tool_output
atelier_repo_map                  atelier_consolidation_inbox
atelier_consolidation_decide
```

There is also a legacy-name alias map at the bottom of `mcp_server.py` (lines ~1722–1747) accepting unprefixed names like `get_reasoning_context`, `check_plan`, etc. **These aliases get deleted too.**

**Docs reference tools that don't exist in code** (phantom tools). These need to be removed from documentation:
`atelier_smart_search`, `atelier_smart_edit`, `atelier_bash_intercept`, `atelier_tool_supervisor`, `atelier_cached_grep`, `atelier_get_run_ledger`, `atelier_update_run_ledger`, `atelier_monitor_event`, `atelier_get_environment`, `atelier_get_environment_context`.

---

## 3. Final Keep List (7)

| Tool | File location now | Action |
|---|---|---|
| `atelier_get_reasoning_context` | mcp_server.py:448 | Keep. Extend return shape to include routing hint (replaces `route_decide`/`route_verify`/`route_contract`). |
| `atelier_check_plan` | mcp_server.py:522 | Keep as-is. |
| `atelier_rescue_failure` | mcp_server.py:809 | Keep as-is. |
| `atelier_record_trace` | mcp_server.py:882 | Keep. Extend response to surface compaction-advice fields (absorbs `compact_advise`). |
| `atelier_run_rubric_gate` | mcp_server.py:1117 | Keep as-is. |
| `atelier_smart_read` | mcp_server.py:1388 | Keep as-is. |
| **`atelier_smart_search`** | NOT IMPLEMENTED | **New work:** implement against existing `capabilities/semantic_file_memory` (and FTS index). Listed in 8+ doc files; ship to match. |

That's it. Everything else goes.

---

## 4. The Cuts (verdict per tool)

### Delete outright (memory — contradicts README)

The README states explicitly: *"Atelier is not a memory system — pair with OpenMemory or Mem0."* Drop these and add a one-paragraph pointer to Letta/Mem0 in the docs where they used to be referenced.

- `atelier_memory_upsert_block`
- `atelier_memory_get_block`
- `atelier_memory_archive`
- `atelier_memory_recall`
- `atelier_memory_summary`

The underlying capabilities (`core/capabilities/archival_recall`, `core/capabilities/memory_arbitration`) — see §6 for whether to delete or keep.

### Delete from MCP, keep CLI (humans, not agents)

These are governance / reporting / inspection that should be human-driven. CLI subcommands stay; MCP registrations and any MCP-only handler code go.

- `atelier_lesson_inbox` → CLI: `atelier lesson inbox` (verify exists; add if missing)
- `atelier_lesson_decide` → CLI: `atelier lesson decide`
- `atelier_consolidation_inbox` → CLI: `atelier consolidation inbox`
- `atelier_consolidation_decide` → CLI: `atelier consolidation decide`
- `atelier_report` → CLI: `atelier report`
- `atelier_sql_inspect` → CLI: `atelier sql inspect`

### Delete outright (redundant or low-value)

- `atelier_batch_edit` — host's `Edit` tool covers this; wrapping creates friction without value.
- `atelier_search_read` — sugar over `smart_search` + `smart_read`; agents can compose.
- `atelier_compact_tool_output` — folds into `record_trace` response (advice, not a separate call). Only delete if the call sites can be ported; if it's used standalone in non-trace flows, fold its body into `smart_read` post-processing instead. Agent must check before deleting.
- `atelier_repo_map` — usage check first. If no caller depends on it, delete. If callers exist, fold output into `get_reasoning_context` return (treat repo map as another retrieval channel).

### Fold into keepers (merge, not delete)

| Source | Fold into | How |
|---|---|---|
| `atelier_route_decide` | `atelier_get_reasoning_context` | Add a `routing` field to the response: `{model_tier, verifier_required, max_tokens_hint}`. |
| `atelier_route_verify` | `atelier_get_reasoning_context` | Add a `verification` field; agents that needed `route_verify` consume this instead. |
| `atelier_route_contract` | `atelier_get_reasoning_context` | Same response. Contract is metadata about the routing decision. |
| `atelier_proof_report` | `atelier_run_rubric_gate` | Make the proof report a field of the rubric-gate result. The error string at mcp_server.py:804 ("Call atelier_proof_report...") needs updating to point users at the new field. |
| `atelier_compress_context` | `atelier_record_trace` | When trace indicates context bloat, the response carries a `compact_recommendation` with the compressed context inline. No separate tool call. |
| `atelier_compact_advise` | `atelier_record_trace` | Same — advice rides on trace responses. |

After folding, the merged callers stop existing as separate MCP entries.

---

## 5. Result

**MCP surface after cut:**

```
atelier_get_reasoning_context   (extended: now includes routing + verification)
atelier_check_plan
atelier_rescue_failure
atelier_record_trace            (extended: now carries compaction advice)
atelier_run_rubric_gate         (extended: now carries proof report)
atelier_smart_read
atelier_smart_search            (newly implemented)
```

7 tools. ~27 → 7. Every removed tool either had a CLI equivalent already, was redundant, contradicted the project identity, or folds cleanly into a keeper.

---

## 6. Files to Touch

### `src/atelier/gateway/adapters/mcp_server.py`

- Delete every `@mcp_tool` block for tools listed in §4 "Delete outright" and §4 "Delete from MCP, keep CLI". For the latter, the underlying capability function may still be reachable via CLI; keep that import path working.
- Delete the legacy-name alias map at the bottom (~lines 1722–1747). All callers use the `atelier_` prefixed names; the unprefixed aliases were transitional and we're not in a transition.
- Extend `atelier_get_reasoning_context` response shape (§4 fold table). Document the new fields with a tested example.
- Extend `atelier_record_trace` and `atelier_run_rubric_gate` similarly.
- Implement `atelier_smart_search` against `capabilities/semantic_file_memory` + FTS index. Cache results on the same path as `smart_read`. Same injection-guard rules as other supervised tools (`capabilities/tool_supervision/search_read.py`).

### `src/atelier/gateway/sdk/mcp.py` (286 lines)

Audit for stale tool references in the client SDK. Anything wrapping a deleted tool gets deleted. SDK should mirror the keep list exactly.

### `src/atelier/gateway/adapters/cli.py`

Verify CLI subcommands exist for everything moved from MCP→CLI in §4. Add any missing:
- `atelier lesson inbox`, `atelier lesson decide`
- `atelier consolidation inbox`, `atelier consolidation decide`
- `atelier report` (already a `[project.scripts]` candidate; check)
- `atelier sql inspect`

### `src/atelier/core/capabilities/`

Per-capability decisions:

| Capability dir | Action |
|---|---|
| `archival_recall/` | Delete if no remaining callers after memory tools go. Otherwise keep; it's used internally. Grep for callers first. |
| `memory_arbitration/` | Same — grep first, delete if orphaned. |
| `lesson_promotion/` | Keep. CLI uses it. |
| `consolidation/` | Keep. CLI uses it. |
| `quality_router/` | Keep. Now feeds `get_reasoning_context` instead of a standalone tool. |
| `proof_gate/` | Keep. Now feeds `run_rubric_gate` response. |
| `context_compression/` | Keep. Now feeds `record_trace` response. |
| `repo_map/` | Decide based on `atelier_repo_map` usage check (§4). |
| `reporting/` | Keep. CLI `atelier report` uses it. |
| `tool_supervision/` | Keep. Powers `smart_read` and the new `smart_search`. |
| `semantic_file_memory/` | Keep. Powers `smart_read` and `smart_search`. |
| `starter_packs.py`, `style_import/` | Untouched. Already CLI-only. |
| `loop_detection/`, `failure_analysis/` | Keep. Feed into `rescue_failure`. |
| `budget_optimizer/` | Keep. Internal. |
| `telemetry/` | Untouched (this is the internal substrate, not the new product telemetry). |

### Tests

Search and update:

```
tests/gateway/test_phase_d3_d4.py:25 references atelier_smart_search (currently fails to find it; will pass after implementation)
tests/**/*.py — grep for every deleted tool name; delete or update tests
```

Any test asserting the deleted tools exist gets deleted. Any test calling the merged behavior via the *old* tool name gets updated to call the new fold target.

### Docs

This is the biggest single chunk of work. Files referencing tools to be cut or phantom tools that don't exist:

```
docs/core/capabilities.md
docs/core/tool-supervision.md
docs/engineering/mcp.md
docs/hosts/all-agent-clis.md
docs/hosts/claude-code.md
docs/hosts/codex.md
docs/hosts/opencode.md
docs/sdk/mcp.md
docs/sdk/python.md
README.md
AGENTS.md
AGENT_README.md
QUICK_REFERENCE.md
src/atelier/gateway/adapters/AGENT_README.md
src/atelier/gateway/sdk/AGENT_README.md
src/atelier/core/capabilities/AGENT_README.md
src/atelier/infra/runtime/AGENT_README.md
GEMINI.atelier.md
```

For each: replace any tool table / capability list with the 7-tool keep list. Remove every reference to phantom tools (§2). Add a short "Why so few tools?" note linking the design rationale (this doc, or its public version).

### `pyproject.toml`

The `[project.scripts]` block already declares `atelier-task`, `atelier-context`, `atelier-check-plan`, `atelier-rescue`, `atelier-bench`. After the cut, ensure scripts exist for the CLI-only governance commands (`atelier-report`?), or accept that they live as subcommands under the main `atelier` entry point. Pick one convention; don't mix.

---

## 7. Phases

### Phase 1 — Safety net (no cuts yet)

- Grep-based usage census: for every tool slated for delete/fold, list all internal callers (test files, doc files, capability-internal calls, SDK wrappers).
- Output: a checklist file `docs/internal/engineering/mcp-cut-census.md` (delete after the cut lands).
- Reason: this is the only way to do hard removal safely without a deprecation period. If the census shows surprises (a test depending on a tool you didn't expect, an SDK wrapper, an example), the cut plan branches before delete.

### Phase 2 — Implement `atelier_smart_search`

- Build the missing tool first, before any deletion. Eight doc files reference it; users may already be reaching for it.
- Mirror `atelier_smart_read`'s shape: same injection-guard rules, cache key strategy, capability backing.

### Phase 3 — Fold the merges

- Extend `atelier_get_reasoning_context` to carry routing + verification + contract fields.
- Extend `atelier_record_trace` to carry compaction advice + compression output.
- Extend `atelier_run_rubric_gate` to carry proof report.
- Update the corresponding capability call paths so the merged tools' bodies live inline in the keeper handlers.

### Phase 4 — Delete

- Remove every `@mcp_tool` block for cuts.
- Remove the legacy alias map.
- Remove orphaned imports.
- Run the census from Phase 1; every flagged caller must be updated or its consumer deleted.

### Phase 5 — Reconcile docs

- Sweep every file in §6 "Docs". Replace tool tables with the 7-tool list. Remove phantom tool references.
- Add a short "Surface area is intentional" paragraph to `README.md` and `docs/engineering/mcp.md` explaining the cut so users don't file issues asking where `atelier_memory_recall` went.

### Phase 6 — Verify

- `mcp-server` boots; advertises exactly 7 tools.
- Each of the 7 is callable end-to-end with a smoke test.
- `grep -rn "atelier_memory\|atelier_route_decide\|atelier_search_read\|atelier_batch_edit\|atelier_compact_advise\|atelier_compress_context\|atelier_compact_tool_output\|atelier_repo_map\|atelier_consolidation_\|atelier_lesson_\|atelier_report\|atelier_sql_inspect\|atelier_route_verify\|atelier_route_contract\|atelier_proof_report"` returns matches only in CHANGELOG and the cut-plan doc itself.
- Phantom tools (§2) no longer appear anywhere in `docs/` or `*.md`.

---

## 8. Risks & How to Handle

| Risk | Handling |
|---|---|
| External users depend on a deleted tool | Project is early-stage OSS; users have been told the surface may move. CHANGELOG entry calls out every removal by name. No grace period. |
| A test depends on a deleted tool and gets deleted with it, hiding a real regression | The Phase 1 census surfaces tests; each flagged test gets a 30-second human review: "is this protecting real behavior, or just asserting the tool exists?" Real-behavior tests get rewritten against the keeper; existence tests get deleted. |
| Folded responses bloat keeper return shapes | Document each new field; require a field to be opt-in via request param if it's expensive to compute (e.g., proof report only when `include_proof=True`). |
| `atelier_repo_map` turns out to be load-bearing | The plan says "decide based on usage check" — don't delete blind. Census in Phase 1 settles this. |
| Capability dirs `archival_recall` / `memory_arbitration` get orphaned | Phase 1 census catches this. Delete the dirs in the same PR if no callers remain — don't leave dead modules. |

---

## 9. Acceptance Criteria

- [ ] `mcp_server.py` registers exactly 7 `@mcp_tool` names, matching §3.
- [ ] No legacy-name alias map remains in `mcp_server.py`.
- [ ] `atelier_smart_search` is implemented and matches the doc claims.
- [ ] Every doc file in §6 has been swept; phantom tools and cut tools no longer appear.
- [ ] `grep` regression check from Phase 6 passes.
- [ ] CLI subcommands exist for every "Delete from MCP, keep CLI" entry in §4.
- [ ] No capability dir is orphaned (zero internal callers and zero CLI/MCP exposure).
- [ ] CHANGELOG entry lists every removed tool by name with a one-line "use X instead" pointer.

---

## 10. Open Items

- `atelier_repo_map` and `atelier_compact_tool_output`: Phase 1 census decides delete vs fold. Don't ship the cut without resolving.
- `archival_recall` / `memory_arbitration` capability dirs: same — delete decision waits on census.
- Whether the `atelier_smart_search` implementation should land in this PR or a prior one. Recommend prior, so the cut PR is purely subtractive plus the three fold extensions.
- Public-facing migration note: do we publish the rationale, or quiet ship? Recommend publish — this is the kind of decision OSS users respect when explained.
