# Phase 1: Grounded Terminal Loop MVP - Research

**Researched:** 2026-06-02  
**Domain:** Search-first grounded terminal workflow over existing Atelier MCP, code-intel, memory, and host surfaces [CITED: .planning/ROADMAP.md]  
**Confidence:** HIGH [CITED: .planning/PROJECT.md]

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Reuse existing Atelier strengths instead of rewriting the stack. [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
- Prioritize research and exploration before implementation. [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
- Prefer correct, non-bloated implementation over heavy validation/tightening loops. [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
- Keep the top-level host/tool experience simple while preserving Atelier's semantic code-intel depth. [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]

### the agent's Discretion
All implementation choices are at the agent's discretion unless a genuine blocker appears. Optimize for the benchmark-first terminal coding agent target: Eval is the execution-discipline reference, Augment is the context-quality reference, and WOZ is the host/tool ergonomics reference. [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]

### Deferred Ideas (OUT OF SCOPE)
- Full host-level routing changes [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
- Minified read/edit path [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
- Benchmark gate implementation [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRND-01 | User can inspect files, paths, and matches through a Search-first default path without manually choosing between overlapping discovery tools. [CITED: .planning/REQUIREMENTS.md] | Use `search` as the default discovery surface, keep `grep` as regex/listing specialist, and unify host rewrites plus tool descriptions around that contract instead of adding a new engine. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/bash_exec.py] |
| GRND-02 | User can move from Search-first results into precise code-intel answers for symbols, callers, usages, and impact in the same session. [CITED: .planning/REQUIREMENTS.md] | Reuse `symbols`/`node`/`callers`/`callees`/`usages`/`impact`/`explore` and bias the default path toward fast escalation rather than replacing these tools. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/code_context/engine.py] |
| GRND-03 | User can batch related edits and follow-up reads through a low-roundtrip grounded terminal workflow. [CITED: .planning/REQUIREMENTS.md] | Reuse `edit` batching, atomic rollback, symbol edits, and post-edit hooks, but keep them behind a grounded search/read first path. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/rich_edit.py; src/atelier/core/capabilities/tool_supervision/post_edit_hooks.py] |
| INTL-01 | User can keep using Atelier's existing memory and context-recall strengths while the benchmark-first reset ships. [CITED: .planning/REQUIREMENTS.md] | Preserve `context`, bootstrap context, archival recall, and `memory` surfaces exactly; simplify the default loop around them rather than around a parallel memory path. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/runtime/engine.py; src/atelier/core/capabilities/archival_recall/capability.py; src/atelier/core/service/bootstrap_context.py] |
| INTL-02 | User can keep using Atelier's existing code-intel strengths while the default terminal path gets simplified. [CITED: .planning/REQUIREMENTS.md] | Keep the current code-intel index, dedicated wrappers, cache, and exploration/context-pack paths intact; Phase 1 should change composition, not capability ownership. [CITED: src/atelier/core/capabilities/code_context/engine.py; src/atelier/gateway/adapters/mcp_server.py; tests/gateway/test_p0_mcp_surfaces.py] |
</phase_requirements>

## Project Constraints (from copilot-instructions.md)

- All Python commands must use `uv run`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]
- Preserve strict dependency direction `gateway -> core -> infra`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]
- Keep entry-point logic thin; new capability logic belongs in `core/capabilities/`, not in `mcp_server.py` or `cli.py`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]
- Claude plugin changes must be made in `integrations/claude/plugin/` and reinstalled with `bash scripts/install_claude.sh`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]
- Do not edit generated instruction artifacts directly; regenerate them from source. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]
- Prefer minimal, surgical changes tied directly to the requested outcome. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]

## Summary

Atelier already has nearly every Phase 1 primitive: `read`, `search`, `grep`, `edit`, `memory`, `context`, `sql`, shell rewrites, dedicated code-intel tools, archival recall, bootstrap context, ledgering, and Claude plugin telemetry. The gap is not missing engines; it is that the default terminal loop is fragmented across overlapping discovery surfaces and multiple escalation paths. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/runtime/engine.py; src/atelier/core/capabilities/code_context/engine.py; integrations/claude/plugin/hooks/session_start.py]

The best Phase 1 shape is a composition change, not a stack rewrite: make ranked `search` the default discovery entry, keep `grep` for regex/listing work, keep `read` for exact file or range reads, and preserve the current code-intel tools as the semantic escalation lane. That matches the roadmap goal, preserves memory/code-intel strengths, and stays benchmark-first by reducing tool-choice churn and roundtrips without inventing a new subsystem. [CITED: .planning/ROADMAP.md; src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py]

**Primary recommendation:** Implement Phase 1 as a thin search-first orchestration layer in `core/capabilities/` plus MCP/host-surface tightening, while leaving the existing read/search/edit/memory/code-intel engines in place. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md; src/atelier/gateway/adapters/mcp_server.py]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Search-first file/path/match discovery | API / Backend [CITED: src/atelier/gateway/adapters/mcp_server.py] | Database / Storage [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] | MCP dispatch and ranking live in backend capability code; caches, ripgrep/Zoekt-backed indexes, and persisted smart state support it. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/smart_search.py] |
| Semantic escalation to symbol/call/usage/impact answers | API / Backend [CITED: src/atelier/core/capabilities/code_context/engine.py] | Database / Storage [CITED: src/atelier/core/capabilities/code_context/engine.py] | Code-intel orchestration is backend-owned, while SQLite/SCIP/cross-lang stores hold the indexed data it queries. [CITED: src/atelier/core/capabilities/code_context/engine.py] |
| Low-roundtrip batched editing | API / Backend [CITED: src/atelier/gateway/adapters/mcp_server.py] | Database / Storage [CITED: src/atelier/infra/runtime/run_ledger.py] | Edit dispatch, rollback, and post-edit hooks run in backend capability code; ledger and workspace state persist results. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/rich_edit.py; src/atelier/infra/runtime/run_ledger.py] |
| Memory/context preservation during the loop | API / Backend [CITED: src/atelier/core/runtime/engine.py] | Database / Storage [CITED: src/atelier/core/capabilities/archival_recall/capability.py; src/atelier/core/service/bootstrap_context.py] | Context assembly is runtime-owned; archival passages, memory blocks, and bootstrap blocks live in store-backed persistence. [CITED: src/atelier/core/runtime/engine.py; src/atelier/core/capabilities/archival_recall/capability.py; src/atelier/core/service/bootstrap_context.py] |
| Host shell/tool ergonomics and nudges | Browser / Client [CITED: integrations/claude/plugin/hooks/pre_tool_use.py; integrations/claude/plugin/hooks/post_tool_use.py] | API / Backend [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Claude hooks and shell rewriting sit at the host edge, but delegate policy and tool surfaces back into the backend. [CITED: integrations/claude/plugin/hooks/pre_tool_use.py; src/atelier/core/capabilities/tool_supervision/bash_exec.py] |

## Standard Stack

**Phase 1 should add no new external packages; the winning stack is the repo's existing search/read/edit/memory/code-intel path. [CITED: .planning/PROJECT.md; src/atelier/gateway/adapters/mcp_server.py]**

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mcp_server.py` tool surface [CITED: src/atelier/gateway/adapters/mcp_server.py] | repo-head [CITED: src/atelier/gateway/adapters/mcp_server.py] | Owns the public `context`, `memory`, `read`, `edit`, `grep`, `search`, `symbols`, `node`, `callers`, `callees`, `impact`, `usages`, `pattern`, and `explore` contracts. [CITED: src/atelier/gateway/adapters/mcp_server.py; tests/gateway/test_p0_mcp_surfaces.py] | Phase 1 needs composition over the existing public tool surface, not a competing surface. [CITED: .planning/ROADMAP.md; src/atelier/gateway/adapters/mcp_server.py] |
| `tool_supervision.smart_search` + `search_read` [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] | repo-head [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] | Provides ranked chunk search, repo-map mode, cache, and fallback read/search composition. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] | This is already the closest internal equivalent to the desired search-first default path. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] |
| `SemanticFileMemoryCapability.smart_read` [CITED: src/atelier/core/capabilities/semantic_file_memory/capability.py] | repo-head [CITED: src/atelier/core/capabilities/semantic_file_memory/capability.py] | Gives exact file/range/full reads plus outline mode for large files. [CITED: src/atelier/core/capabilities/semantic_file_memory/capability.py] | It already lowers read cost without removing precise file access. [CITED: src/atelier/core/capabilities/semantic_file_memory/capability.py] |
| `CodeContextEngine` [CITED: src/atelier/core/capabilities/code_context/engine.py] | repo-head [CITED: src/atelier/core/capabilities/code_context/engine.py] | Provides indexed symbol search, node lookup, explore, usages, call graph, impact, context packs, and rename support. [CITED: src/atelier/core/capabilities/code_context/engine.py] | This is the semantic moat Phase 1 must preserve as the escalation lane. [CITED: .planning/research/AUGMENT-PARITY.md; src/atelier/core/capabilities/code_context/engine.py] |
| `tool_smart_edit` + `rich_edit` [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/rich_edit.py] | repo-head [CITED: src/atelier/gateway/adapters/mcp_server.py] | Supports batched file edits, symbol edits, rollback, and post-edit hooks. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/rich_edit.py] | Low-roundtrip execution should use existing batch-edit machinery rather than rebuilding edit orchestration. [CITED: src/atelier/gateway/adapters/mcp_server.py] |
| `AtelierRuntimeCore.get_context` + archival recall [CITED: src/atelier/core/runtime/engine.py; src/atelier/core/capabilities/archival_recall/capability.py] | repo-head [CITED: src/atelier/core/runtime/engine.py] | Composes procedures, bootstrap context, memory facts, and archival passages. [CITED: src/atelier/core/runtime/engine.py] | Phase 1 must simplify the loop without cutting this context quality. [CITED: .planning/research/AUGMENT-PARITY.md; .planning/REQUIREMENTS.md] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `native_search.py` [CITED: src/atelier/core/capabilities/tool_supervision/native_search.py] | repo-head [CITED: src/atelier/core/capabilities/tool_supervision/native_search.py] | Regex/glob/type-filter search for `grep`. [CITED: src/atelier/core/capabilities/tool_supervision/native_search.py] | Use for exact pattern search, file listings, summaries, and reruns. [CITED: src/atelier/gateway/adapters/mcp_server.py] |
| `bash_exec.py` [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | repo-head [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Rewrites `cat`, `rg`, and `grep` shell commands into Atelier `read`/`grep`, and blocks destructive shell patterns. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Use to keep host shell behavior aligned with the search-first loop. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] |
| Claude hooks + `plugin_runtime.py` [CITED: integrations/claude/plugin/hooks/session_start.py; integrations/claude/plugin/hooks/pre_tool_use.py; integrations/claude/plugin/hooks/post_tool_use.py; src/atelier/core/capabilities/plugin_runtime.py] | repo-head [CITED: integrations/claude/plugin/hooks/session_start.py] | Captures session state, telemetry, savings, and soft tool nudges. [CITED: integrations/claude/plugin/hooks/session_start.py; integrations/claude/plugin/hooks/session_telemetry.py] | Use for host-side ergonomics and benchmark-relevant telemetry, not for core business logic. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md] |
| `RunLedger` [CITED: src/atelier/infra/runtime/run_ledger.py] | repo-head [CITED: src/atelier/infra/runtime/run_ledger.py] | Persists tool calls, file edits, command results, and token/cost metadata. [CITED: src/atelier/infra/runtime/run_ledger.py] | Use to preserve traceability while tightening the default loop. [CITED: .planning/PROJECT.md; src/atelier/infra/runtime/run_ledger.py] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Composing the existing `search` + code-intel stack [CITED: src/atelier/gateway/adapters/mcp_server.py] | A brand-new omnibus Phase 1 search tool [ASSUMED] | New surface area would duplicate working engines and increase regression risk in a brownfield retrofit. [CITED: .planning/PROJECT.md; /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md] |
| Keeping `grep` and `search` distinct [CITED: src/atelier/gateway/adapters/mcp_server.py] | Merging regex and ranked search into one ambiguous contract [ASSUMED] | Distinct contracts already map cleanly to exact-pattern vs ranked-discovery use cases; blurring them would raise tool-selection ambiguity again. [CITED: src/atelier/gateway/adapters/mcp_server.py; tests/gateway/test_p0_mcp_surfaces.py] |
| Preserving dedicated code-intel wrappers [CITED: src/atelier/gateway/adapters/mcp_server.py] | Replacing them with generic snippet search only [ASSUMED] | That would directly regress exact callers/usages/impact behavior already covered by the current engine and tests. [CITED: src/atelier/core/capabilities/code_context/engine.py; tests/core/test_code_context.py] |

**Installation:** No new package installation is recommended for Phase 1. [CITED: .planning/PROJECT.md]

## Most Likely Files to Change

| File | Why it is likely to change |
|------|-----------------------------|
| `src/atelier/gateway/adapters/mcp_server.py` [CITED: src/atelier/gateway/adapters/mcp_server.py] | Public MCP descriptions, tool dispatch, and any search-first contract tightening land here, even if the underlying logic should move into `core/capabilities/`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md; src/atelier/gateway/adapters/mcp_server.py] |
| `src/atelier/core/capabilities/tool_supervision/smart_search.py` [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] | This already owns ranked `search`; Phase 1 likely needs ranking, output-shape, or escalation metadata changes here. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] |
| `src/atelier/core/capabilities/tool_supervision/search_read.py` [CITED: src/atelier/core/capabilities/tool_supervision/search_read.py] | This module already collapses `grep -> read` loops and is the most natural place to deepen low-roundtrip grounded search behavior. [CITED: src/atelier/core/capabilities/tool_supervision/search_read.py] |
| `src/atelier/core/capabilities/code_context/engine.py` [CITED: src/atelier/core/capabilities/code_context/engine.py] | Phase 1 should make semantic escalation cheaper and clearer; that usually means minor payload/view changes here, not engine replacement. [CITED: src/atelier/core/capabilities/code_context/engine.py] |
| `src/atelier/core/capabilities/semantic_file_memory/capability.py` [CITED: src/atelier/core/capabilities/semantic_file_memory/capability.py] | `read` behavior already depends on this module for outline/range/full mode, so preserving low-cost grounded reads may require small adjustments here. [CITED: src/atelier/core/capabilities/semantic_file_memory/capability.py] |
| `src/atelier/core/capabilities/tool_supervision/bash_exec.py` [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Shell rewrite behavior is part of the low-roundtrip story; any search-first default path should stay consistent with it. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] |
| `integrations/claude/plugin/hooks/pre_tool_use.py` [CITED: integrations/claude/plugin/hooks/pre_tool_use.py] | Soft nudges toward grounding or edit batching are host-ergonomics work and belong here if added in Phase 1. [CITED: integrations/claude/plugin/hooks/pre_tool_use.py] |
| `tests/gateway/test_p0_mcp_surfaces.py`, `tests/gateway/test_mcp_tool_handlers.py`, `tests/core/test_code_context.py` [CITED: tests/gateway/test_p0_mcp_surfaces.py; tests/gateway/test_mcp_tool_handlers.py; tests/core/test_code_context.py] | These already cover the Phase 1 tool contract and code-intel guarantees, so they should absorb the main regression checks. [CITED: tests/gateway/test_p0_mcp_surfaces.py; tests/gateway/test_mcp_tool_handlers.py; tests/core/test_code_context.py] |

## Architecture Patterns

### System Architecture Diagram

```text
Host / Claude / Copilot / CLI
        |
        v
MCP gateway + shell rewrite layer
(`search`, `grep`, `read`, `edit`, `symbols`, `node`, ...)
        |
        +------------------------------+
        |                              |
        v                              v
Search-first discovery path        Context / memory path
`smart_search` + `grep` +          `context` + bootstrap +
`search_read` + `smart_read`       archival recall + memory facts
        |                              |
        +--------------+---------------+
                       |
                       v
Semantic escalation lane
`CodeContextEngine`
(`symbols` / `node` / `callers` / `usages` / `impact` / `explore`)
                       |
                       v
Batch execution lane
`edit` -> `rich_edit` -> post-edit hooks -> ledger
                       |
                       v
Persistent state
code_context.sqlite / smart_state.json / memory store / run ledger / session_state.json
```

### Recommended Project Structure

```text
src/atelier/core/capabilities/
├── grounded_loop/          # NEW thin Phase-1 composition logic if needed
├── tool_supervision/       # keep ranked search / grep / shell rewrite / edit batching here
├── code_context/           # preserve semantic escalation here
└── semantic_file_memory/   # preserve read/outline behavior here

src/atelier/gateway/adapters/
└── mcp_server.py           # dispatch + schema descriptions only

integrations/claude/plugin/hooks/
└── pre_tool_use.py         # host nudges only, if Phase 1 adds them
```

### Pattern 1: Search-first composition over existing surfaces
**What:** Make `search` the default repo-discovery entry, with `grep` for exact regex/listing work and `read` for precise file/range inspection. [CITED: src/atelier/gateway/adapters/mcp_server.py]  
**When to use:** Default terminal exploration, especially when the user does not yet know the exact file or symbol. [CITED: .planning/ROADMAP.md]  
**Example:**
```json
// Source: src/atelier/gateway/adapters/mcp_server.py
{"name":"search","arguments":{"query":"session telemetry hook","path":".","mode":"chunks","max_files":8,"budget_tokens":2000}}
```

### Pattern 2: Semantic escalation as the second hop
**What:** After `search` grounds the area, jump into `node`, `callers`, `callees`, `usages`, `impact`, or `explore` instead of continuing with more fuzzy search. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/code_context/engine.py]  
**When to use:** Symbol-focused questions, blast-radius checks, or multi-file understanding after initial grounding. [CITED: .planning/REQUIREMENTS.md]  
**Example:**
```json
// Source: src/atelier/gateway/adapters/mcp_server.py
{"name":"explore","arguments":{"query":"session telemetry","seed_files":["integrations/claude/plugin/hooks/session_telemetry.py"],"max_files":6}}
```

### Pattern 3: Batch edits after grounding, not before
**What:** Use one `edit` call with multiple descriptors and atomic rollback instead of repeated one-off edit calls. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/rich_edit.py]  
**When to use:** Once search/read/code-intel has identified the touched files or symbols. [CITED: .planning/REQUIREMENTS.md]  
**Example:**
```json
// Source: src/atelier/gateway/adapters/mcp_server.py
{
  "name":"edit",
  "arguments":{
    "edits":[
      {"file_path":"src/a.py","old_string":"foo","new_string":"bar"},
      {"file_path":"src/b.py","old_string":"foo","new_string":"bar"}
    ],
    "atomic":true
  }
}
```

### Anti-Patterns to Avoid
- **New gateway-only orchestrator:** Do not bury new Phase 1 behavior inside `mcp_server.py`; keep dispatch thin and move composition into `core/capabilities/`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]
- **Search-only simplification:** Do not simplify the terminal loop by hiding or removing exact semantic tools. [CITED: .planning/REQUIREMENTS.md; src/atelier/core/capabilities/code_context/engine.py]
- **Validation-loop creep:** Do not turn Phase 1 into a heavy edit-gating or benchmark-gating project; those belong mainly to later phases. [CITED: .planning/ROADMAP.md; .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Search-first discovery | A new bespoke repo search engine [ASSUMED] | `search` + `smart_search` + `search_read` + `grep` [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] | The repo already has ranked search, regex search, fallback reads, cache, and optional Zoekt routing. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] |
| Exact symbol reasoning | Regex-only symbol tracing [ASSUMED] | `CodeContextEngine` via `symbols` / `node` / `callers` / `callees` / `usages` / `impact` / `explore` [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/code_context/engine.py] | Current code-intel already covers exact symbol/index/call-graph operations and has tests. [CITED: tests/core/test_code_context.py] |
| Batched edit execution | Ad-hoc looped string replacements [ASSUMED] | `edit` + `rich_edit` + `post_edit_hooks` [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/rich_edit.py; src/atelier/core/capabilities/tool_supervision/post_edit_hooks.py] | Existing edit machinery already supports atomic batching, notebook edits, symbol edits, and diagnostics. [CITED: src/atelier/gateway/adapters/mcp_server.py] |
| Shell-level grounding policy | A second command classifier [ASSUMED] | `bash_exec.classify_command()` and current shell rewrites [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | The current shell tool already rewrites `cat`/`rg`/`grep` and blocks destructive commands. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] |
| Memory/context preservation | A parallel Phase-1 memory stack [ASSUMED] | `context`, bootstrap context, archival recall, and `memory` [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/runtime/engine.py; src/atelier/core/capabilities/archival_recall/capability.py] | Current context assembly already composes reason blocks, bootstrap blocks, memory facts, and archival recall. [CITED: src/atelier/core/runtime/engine.py] |

**Key insight:** Phase 1 is mostly an orchestration and contract-tightening problem; most capability regressions will come from bypassing existing engines, not from missing libraries. [CITED: .planning/PROJECT.md; src/atelier/gateway/adapters/mcp_server.py]

## Common Pitfalls

### Pitfall 1: Replacing semantic code-intel with generic ranked search
**What goes wrong:** Users can find files faster but lose exact callers/usages/impact answers. [CITED: .planning/REQUIREMENTS.md; src/atelier/core/capabilities/code_context/engine.py]  
**Why it happens:** `search` and `grep` are easier to reach than the code-intel wrappers, so simplification work can accidentally stop there. [CITED: src/atelier/gateway/adapters/mcp_server.py]  
**How to avoid:** Treat search as the default entry and code-intel as the default escalation, not as competing features. [CITED: .planning/ROADMAP.md]  
**Warning signs:** Phase 1 patches touch `search`/`grep` descriptions or routing but do not preserve tests for `node`, `callers`, `usages`, `impact`, and `explore`. [CITED: tests/gateway/test_p0_mcp_surfaces.py; tests/core/test_code_context.py]

### Pitfall 2: Putting new logic in the gateway layer
**What goes wrong:** `mcp_server.py` grows further into a policy engine and becomes harder to reason about. [CITED: src/atelier/gateway/adapters/mcp_server.py]  
**Why it happens:** Phase 1 behavior is visible at the MCP surface, so it is tempting to implement everything there. [CITED: src/atelier/gateway/adapters/mcp_server.py]  
**How to avoid:** Add any new search-first orchestration as a core capability and keep MCP changes limited to schema/dispatch. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]  
**Warning signs:** New stateful ranking, loop policy, or escalation heuristics appear directly in `mcp_server.py`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]

### Pitfall 3: Regressing host shell behavior
**What goes wrong:** Native `cat`/`rg`/`grep` usage no longer aligns with the intended grounded loop, or destructive command safety weakens. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py]  
**Why it happens:** Search-first work modifies tool defaults but forgets the shell rewrite path. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py]  
**How to avoid:** Keep the shell rewrite policy and the MCP tool contract synchronized. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py; src/atelier/gateway/adapters/mcp_server.py]  
**Warning signs:** `search`/`grep` behavior changes but `bash_exec.classify_command()` still rewrites to old semantics. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py]

### Pitfall 4: Making the loop depend on optional indexes
**What goes wrong:** Search quality collapses or errors when Zoekt or fresh code indexes are unavailable. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py]  
**Why it happens:** The repo already supports Zoekt, SCIP, and caches, so it is easy to over-assume they are present and fresh. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py]  
**How to avoid:** Keep ripgrep/local-search/local-index fallbacks as the success path, with Zoekt as acceleration only. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py]  
**Warning signs:** Phase 1 code assumes `backend == "zoekt"` or requires manual indexing before any useful answer. [CITED: tests/gateway/test_p0_mcp_surfaces.py]

### Pitfall 5: Losing memory/bootstrap context during simplification
**What goes wrong:** The terminal loop becomes cheaper but less context-aware on real repo tasks. [CITED: .planning/research/AUGMENT-PARITY.md; src/atelier/core/runtime/engine.py]  
**Why it happens:** Search-first changes can accidentally bypass `context`, bootstrap blocks, or recall flows. [CITED: src/atelier/core/runtime/engine.py; src/atelier/core/service/bootstrap_context.py]  
**How to avoid:** Keep `context` as the session-seeding step and preserve `agent_id`-scoped recall behavior. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/runtime/engine.py]  
**Warning signs:** Search-first patches stop calling `get_context`, remove `bootstrap` payloads, or ignore `recalled_passages`. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/runtime/engine.py]

## Code Examples

Verified patterns from repository sources:

### Default discovery
```json
// Source: src/atelier/gateway/adapters/mcp_server.py
{"name":"search","arguments":{"query":"run ledger session stats","path":".","mode":"chunks","max_files":8,"budget_tokens":2000}}
```

### Exact semantic escalation
```json
// Source: src/atelier/gateway/adapters/mcp_server.py
{"name":"callers","arguments":{"symbol":"RunLedger.record_tool_call","depth":1,"limit":20}}
```

### Grounded batched edit
```json
// Source: src/atelier/gateway/adapters/mcp_server.py
{
  "name":"edit",
  "arguments":{
    "edits":[
      {"kind":"symbol","qualified_name":"atelier.gateway.adapters.mcp_server.tool_smart_search","mode":"replace","new_body":"..."},
      {"file_path":"tests/gateway/test_p0_mcp_surfaces.py","old_string":"old","new_string":"new"}
    ],
    "atomic":true,
    "post_edit_hooks":true
  }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Shell `cat` / `rg` / `grep` directly in the terminal [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Shell policy rewrites `cat` to `read` and `rg`/`grep` to Atelier `grep`, while blocking destructive shell families. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Observed in current repo. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Phase 1 should extend this grounded path instead of bypassing it. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] |
| Monolithic internal `code` op knowledge [CITED: tests/gateway/test_p0_mcp_surfaces.py] | Dedicated discoverable MCP tools now exist for `node`, `callers`, `callees`, `impact`, `usages`, `pattern`, and `explore`, while the multiplexer remains under `symbols`. [CITED: src/atelier/gateway/adapters/mcp_server.py; tests/gateway/test_p0_mcp_surfaces.py] | Observed in current repo. [CITED: tests/gateway/test_p0_mcp_surfaces.py] | Phase 1 should capitalize on better tool discoverability instead of collapsing back to a hidden multiplexer. [CITED: src/atelier/gateway/adapters/mcp_server.py] |
| Older `code` ops for `routes`, `status`, `files`, and `context` [CITED: src/atelier/gateway/adapters/mcp_server.py] | Those ops are retired; `context mode='symbols'` and `grep` are the intended replacements. [CITED: src/atelier/gateway/adapters/mcp_server.py] | Observed in current repo. [CITED: src/atelier/gateway/adapters/mcp_server.py] | Do not plan Phase 1 around reviving retired op shapes. [CITED: src/atelier/gateway/adapters/mcp_server.py] |

**Deprecated/outdated:**
- `code` op aliases as a user-facing mental model are outdated; the tests explicitly keep the internal alias hidden from public discovery. [CITED: tests/gateway/test_p0_mcp_surfaces.py]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A brand-new omnibus Phase 1 search tool would be worse than composing the current surfaces. [ASSUMED] | Standard Stack / Alternatives Considered | Could bias implementation away from a new wrapper that might benchmark better if user-facing tool choice remains too confusing. [ASSUMED] |
| A2 | Merging `grep` and ranked `search` into one ambiguous contract would hurt usability. [ASSUMED] | Standard Stack / Alternatives Considered | Could miss a better contract if benchmark evidence shows one-surface search is superior. [ASSUMED] |
| A3 | Looping ad-hoc string replacements would be worse than current batched edit machinery for Phase 1. [ASSUMED] | Don't Hand-Roll | Low risk; current code strongly suggests this, but the claim is still comparative rather than directly measured here. [CITED: src/atelier/core/capabilities/tool_supervision/rich_edit.py] |

## Open Questions

1. **Should Phase 1 expose a new thin top-level grounded-loop capability, or only retune the existing tool contracts?**
   - What we know: The repo already has the necessary engines, and the architecture guidance says new behavior belongs in `core/capabilities/`, not `mcp_server.py`. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md; src/atelier/gateway/adapters/mcp_server.py]
   - What's unclear: Whether benchmark wins require a visible new wrapper surface or only better defaults/descriptions/escalation hints. [ASSUMED]
   - Recommendation: Start with a thin core capability plus minimal MCP contract tightening; only add a new user-facing tool if tool-choice ambiguity remains in benchmark runs. [CITED: .planning/PROJECT.md; /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md]

2. **Should Phase 1 add hard edit-grounding gates?**
   - What we know: Hard grounded edit discipline is explicitly a Phase 2 requirement, and the user asked not to overfocus on validation loops in Phase 1. [CITED: .planning/ROADMAP.md; .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
   - What's unclear: Whether a very light soft gate in the host hook would help solved-rate without adding friction. [ASSUMED]
   - Recommendation: Keep Phase 1 to soft nudges only; reserve hard gates for Phase 2. [CITED: .planning/ROADMAP.md]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` [VERIFIED: codebase grep] | Repo-standard Python execution [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md] | ✓ [VERIFIED: codebase grep] | `uv 0.11.7` [VERIFIED: codebase grep] | — |
| `rg` [VERIFIED: codebase grep] | `grep`, `search_read`, and text fallback paths [CITED: src/atelier/core/capabilities/tool_supervision/native_search.py; src/atelier/core/capabilities/code_context/engine.py] | ✓ [VERIFIED: codebase grep] | `ripgrep 14.1.1` [VERIFIED: codebase grep] | Python fallback exists for some paths, but `rg` is the preferred fast path. [CITED: src/atelier/core/capabilities/code_context/engine.py] |
| `node` / `npm` [VERIFIED: codebase grep] | Optional frontend/docs/tooling surfaces; not Phase 1 critical. [CITED: .planning/PROJECT.md] | ✓ [VERIFIED: codebase grep] | `node v24.12.0`, `npm 11.6.2` [VERIFIED: codebase grep] | Not needed for the core Phase 1 loop. [CITED: .planning/PROJECT.md] |
| `docker` [VERIFIED: codebase grep] | Optional Zoekt sidecar path and local stack support. [CITED: src/atelier/gateway/cli/commands/code.py; src/atelier/core/capabilities/tool_supervision/smart_search.py] | ✓ [VERIFIED: codebase grep] | `Docker 29.1.3` [VERIFIED: codebase grep] | Local ripgrep and local code index paths still work without it. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py] |
| Zoekt binaries [VERIFIED: codebase grep] | Optional large-repo acceleration for ranked search. [CITED: src/atelier/gateway/cli/commands/code.py; src/atelier/core/capabilities/tool_supervision/smart_search.py] | ✗ [VERIFIED: codebase grep] | — | Built-in fallback is ripgrep/local search; Go is present for later install if needed. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/gateway/cli/commands/code.py] |

**Missing dependencies with no fallback:**
- None for Phase 1 research scope. [VERIFIED: codebase grep]

**Missing dependencies with fallback:**
- Zoekt binaries are missing, but current `search`/`grep`/code-intel paths degrade to local fallbacks. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no [CITED: .planning/ROADMAP.md] | Phase 1 is not adding auth flows. [CITED: .planning/ROADMAP.md] |
| V3 Session Management | yes [CITED: integrations/claude/plugin/hooks/session_start.py; src/atelier/infra/runtime/run_ledger.py] | Session state and ledger correlation already run through `session_state.json` and `RunLedger`. [CITED: integrations/claude/plugin/hooks/session_start.py; src/atelier/infra/runtime/run_ledger.py] |
| V4 Access Control | yes [CITED: src/atelier/core/capabilities/tool_supervision/rich_edit.py] | Path safety and protected-path denial in edit/search helpers prevent workspace escape. [CITED: src/atelier/core/capabilities/tool_supervision/rich_edit.py; src/atelier/core/capabilities/tool_supervision/native_search.py] |
| V5 Input Validation | yes [CITED: src/atelier/gateway/adapters/mcp_server.py] | Pydantic MCP schemas plus explicit query/path validation in search and shell code. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] |
| V6 Cryptography | no [CITED: .planning/ROADMAP.md] | Phase 1 does not introduce new cryptographic requirements. [CITED: .planning/ROADMAP.md] |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal / workspace escape [CITED: src/atelier/core/capabilities/tool_supervision/rich_edit.py; src/atelier/core/capabilities/tool_supervision/native_search.py] | Tampering | Use `_safe_resolve()`-style path normalization and protected path checks; do not bypass them in Phase 1 wrappers. [CITED: src/atelier/core/capabilities/tool_supervision/rich_edit.py; src/atelier/core/capabilities/tool_supervision/native_search.py] |
| Shell injection via search/read shortcuts [CITED: src/atelier/core/capabilities/tool_supervision/search_read.py; src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Tampering | Preserve `_assert_safe_args()` / `_assert_safe_query()` and `classify_command()` rewriting/blocking. [CITED: src/atelier/core/capabilities/tool_supervision/search_read.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/bash_exec.py] |
| Destructive shell execution (`rm -rf`, `git reset --hard`, `git clean -fd`) [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] | Denial of Service | Keep the current blocked-command policy in the shell path. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py] |
| Overbroad SQL writes during convenience tooling [CITED: src/atelier/gateway/adapters/mcp_server.py] | Tampering | Keep `tool_sql` bounded and respect `allow_writes` / row limits if SQL ergonomics are surfaced in later loop work. [CITED: src/atelier/gateway/adapters/mcp_server.py] |

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` - project goals, constraints, and reset framing. [CITED: .planning/PROJECT.md]
- `.planning/REQUIREMENTS.md` - Phase 1 requirement definitions. [CITED: .planning/REQUIREMENTS.md]
- `.planning/ROADMAP.md` - phase goal, success criteria, and scope boundaries. [CITED: .planning/ROADMAP.md]
- `.planning/research/RESET-RESEARCH.md` - prior reset conclusions about Eval/WOZ/benchmark framing. [CITED: .planning/research/RESET-RESEARCH.md]
- `.planning/research/AUGMENT-PARITY.md` - parity goals that matter for this reset. [CITED: .planning/research/AUGMENT-PARITY.md]
- `.planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md` - user constraints and phase boundary. [CITED: .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]
- `src/atelier/gateway/adapters/mcp_server.py` - live MCP tool contracts and fragmentation points. [CITED: src/atelier/gateway/adapters/mcp_server.py]
- `src/atelier/core/capabilities/tool_supervision/smart_search.py` - current ranked search implementation. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py]
- `src/atelier/core/capabilities/tool_supervision/search_read.py` - current combined search/read path. [CITED: src/atelier/core/capabilities/tool_supervision/search_read.py]
- `src/atelier/core/capabilities/semantic_file_memory/capability.py` - current read/outline behavior. [CITED: src/atelier/core/capabilities/semantic_file_memory/capability.py]
- `src/atelier/core/capabilities/code_context/engine.py` - current semantic escalation capabilities. [CITED: src/atelier/core/capabilities/code_context/engine.py]
- `src/atelier/core/runtime/engine.py` - current context/memory composition. [CITED: src/atelier/core/runtime/engine.py]
- `src/atelier/core/capabilities/tool_supervision/bash_exec.py` - shell rewrite and safety behavior. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py]
- `integrations/claude/plugin/hooks/*.py` - host-side session/tool ergonomics and telemetry. [CITED: integrations/claude/plugin/hooks/session_start.py; integrations/claude/plugin/hooks/pre_tool_use.py; integrations/claude/plugin/hooks/post_tool_use.py; integrations/claude/plugin/hooks/session_telemetry.py; integrations/claude/plugin/hooks/stop.py]
- `tests/gateway/test_p0_mcp_surfaces.py`, `tests/gateway/test_mcp_tool_handlers.py`, `tests/core/test_code_context.py` - current contract and regression expectations. [CITED: tests/gateway/test_p0_mcp_surfaces.py; tests/gateway/test_mcp_tool_handlers.py; tests/core/test_code_context.py]

### Secondary (MEDIUM confidence)
- `.planning/research/SUMMARY.md` - synthesized project-level reset summary. [CITED: .planning/research/SUMMARY.md]

### Tertiary (LOW confidence)
- None. [VERIFIED: codebase grep]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - recommendations are based on current repository code and locked brownfield constraints. [CITED: .planning/PROJECT.md; src/atelier/gateway/adapters/mcp_server.py]
- Architecture: HIGH - the current responsibility split and likely change points are directly visible in the codebase. [CITED: /home/pankaj/Projects/leanchain/atelier/copilot-instructions.md; src/atelier/core/capabilities/code_context/engine.py]
- Pitfalls: HIGH - they follow directly from current overlap, existing tests, and locked phase boundaries. [CITED: .planning/ROADMAP.md; tests/gateway/test_p0_mcp_surfaces.py]

**Research date:** 2026-06-02  
**Valid until:** 2026-07-02 for repo-structure guidance; re-check sooner if the MCP tool surface or code-intel engine changes materially. [ASSUMED]
