# Phase 1: Grounded Terminal Loop MVP - Research

**Researched:** 2026-06-02
**Domain:** Search-first grounded terminal loop over existing Atelier MCP/core capabilities
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Reuse existing Atelier strengths instead of rewriting the stack.
- Prioritize research and exploration before implementation.
- Prefer correct, non-bloated implementation over heavy validation/tightening loops.
- Keep the top-level host/tool experience simple while preserving Atelier's semantic code-intel depth.

### the agent's Discretion
All implementation choices are at the agent's discretion unless a genuine blocker appears. Optimize for the benchmark-first terminal coding agent target: Eval is the execution-discipline reference, Augment is the context-quality reference, and WOZ is the host/tool ergonomics reference.

### Deferred Ideas (OUT OF SCOPE)
- Full host-level routing changes
- Minified read/edit path
- Benchmark gate implementation
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRND-01 | User can inspect files, paths, and matches through a Search-first default path without manually choosing between overlapping discovery tools | Reuse `search_first` over `smart_search`, keep `search` as the ranked default, and preserve explicit `grep` for regex/glob discovery. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/gateway/adapters/mcp_server.py; tests/core/capabilities/grounded_loop/test_search_first.py; tests/gateway/test_p0_mcp_surfaces.py] |
| GRND-02 | User can move from Search-first results into precise code-intel answers for symbols, callers, usages, and impact in the same session | Keep dedicated `node`, `callers`, `callees`, `usages`, `impact`, and `explore` tools visible and route grounded `seed_files` into `CodeContextEngine`. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/code_context/engine.py; tests/gateway/test_mcp_tool_handlers.py; tests/core/test_code_context.py] |
| GRND-03 | User can batch related edits and follow-up reads through a low-roundtrip grounded terminal workflow | Reuse `edit` rich/batch descriptors, diff recording, and `calls_saved`; keep `search_first` handoffs explicit for `read`, `context`, and `explore`. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/grounded_loop/search_first.py; tests/core/capabilities/grounded_loop/test_search_first.py] |
| INTL-01 | User can keep using Atelier's existing memory and context-recall strengths while the benchmark-first reset ships | Preserve `context`/memory follow-ups from grounded results and keep session-start warming and plugin runtime bootstrap intact. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/core/runtime/engine.py; integrations/claude/plugin/hooks/session_start.py; src/atelier/core/capabilities/plugin_runtime.py] |
| INTL-02 | User can keep using Atelier's existing code-intel strengths while the default terminal path gets simplified | Keep semantic escalation in `CodeContextEngine`; do not replace it with search-only heuristics. [CITED: src/atelier/core/capabilities/code_context/engine.py; src/atelier/gateway/adapters/mcp_server.py; tests/core/test_code_context.py] |
</phase_requirements>

## Summary

Phase 1 should remain a composition pass, not a rewrite: `search_first` already wraps existing `smart_search`, returns explicit `read`/`context`/`explore` handoffs, and computes `calls_saved` from grouped matches. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; tests/core/capabilities/grounded_loop/test_search_first.py]

The correct implementation center is `core`, not `gateway`: the MCP `search`, `read`, `edit`, and dedicated code-intel tools are thin adapters over `smart_search`, semantic file memory, batch/rich edit helpers, and `CodeContextEngine`, and tests explicitly lock in that grounded `seed_files` pass through to engine ranking instead of adding new gateway ranking logic. [CITED: CLAUDE.md; src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py; tests/gateway/test_mcp_tool_handlers.py]

Benchmark-sensitive risk is not missing a new feature; it is regressing solved-rate by hiding semantic escalation, muddying search-vs-grep affordances, or bloating the host loop with hard gates that Phase 1 intentionally defers. [CITED: .planning/ROADMAP.md; .planning/STATE.md; src/atelier/gateway/adapters/mcp_server.py; integrations/claude/plugin/hooks/pre_tool_use.py]

**Primary recommendation:** Keep Phase 1 as a search-first grounding composition pass over existing `search`/`read`/`edit`/`context`/code-intel surfaces, preserve explicit semantic escalation, and limit host ergonomics changes to advisory nudges plus generated guidance. [CITED: .planning/PROJECT.md; .planning/STATE.md; src/atelier/core/capabilities/grounded_loop/search_first.py; docs/agent-os/modes/code.md]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Search-first discovery ranking | Core capability layer | Gateway MCP adapter | `search_first` and `smart_search` live in `core`, while MCP `search` only forwards arguments and strips metadata. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/gateway/adapters/mcp_server.py] |
| Exact file reads and lightweight outlines | Gateway MCP adapter | Core semantic file memory | `tool_smart_read` is the entry surface, but the actual outline/full/range behavior comes from semantic file memory helpers. [CITED: src/atelier/gateway/adapters/mcp_server.py] |
| Semantic escalation (`node`/`callers`/`callees`/`usages`/`impact`/`explore`) | Core code-intel engine | Gateway MCP wrappers | Dedicated MCP tools are thin wrappers over `CodeContextEngine` operations. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/code_context/engine.py] |
| Batched grounded edits | Core tool supervision | Gateway MCP adapter | `edit` validates descriptor families in the gateway, then delegates to batch/rich edit implementations and post-edit hooks. [CITED: src/atelier/gateway/adapters/mcp_server.py] |
| Host/tool ergonomics and advisory nudges | Claude plugin/hooks | Core session optimizer | Hook wiring lives in the Claude plugin, while guidance text is built from shared core optimizer/plugin runtime code. [CITED: integrations/claude/plugin/hooks/hooks.json; integrations/claude/plugin/hooks/session_start.py; src/atelier/core/capabilities/session_optimizer.py; src/atelier/core/capabilities/plugin_runtime.py] |
| Session/run trace continuity | Infra runtime ledger | Gateway/plugin callers | MCP and plugin hooks append session/file-edit events into run ledger state under `~/.atelier`. [CITED: CLAUDE.md; integrations/claude/plugin/hooks/session_start.py; integrations/claude/plugin/hooks/post_tool_use.py] |

## Project Constraints (from copilot-instructions.md)

- All Python commands must use `uv run`. [CITED: CLAUDE.md]
- Keep `gateway -> core -> infra` dependency direction intact, and keep entry points thin. [CITED: CLAUDE.md]
- New capability behavior belongs in `src/atelier/core/capabilities/`, not `mcp_server.py` or CLI dispatchers. [CITED: CLAUDE.md]
- After changing Claude plugin files, reinstall with `bash scripts/install_claude.sh`. [CITED: CLAUDE.md]
- Do not edit generated host/agent files directly; edit source material and regenerate. [CITED: CLAUDE.md; integrations/claude/plugin/agents/code.md]
- Prefer surgical changes tied directly to the phase goal; avoid speculative abstractions or adjacent refactors. [CITED: CLAUDE.md]

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `atelier.core.capabilities.grounded_loop.search_first` | repo HEAD [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py] | Search-first orchestration envelope | Already composes ranked discovery plus explicit `read`/`context`/`explore` handoff payloads, which matches Phase 1 exactly. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; tests/core/capabilities/grounded_loop/test_search_first.py] |
| `atelier.core.capabilities.tool_supervision.smart_search` | repo HEAD [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] | Ranked grounding across ripgrep/semantic/graph signals with optional Zoekt routing | It already fuses lexical, semantic, and graph ranking and falls back cleanly from optional backend routing. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] |
| `atelier.core.capabilities.code_context.CodeContextEngine` | repo HEAD [CITED: src/atelier/core/capabilities/code_context/engine.py] | Semantic escalation for symbol/context/call-graph/impact/explore | Existing engine already prioritizes grounded `seed_files` and enforces token-budgeted outputs. [CITED: src/atelier/core/capabilities/code_context/engine.py; tests/core/test_code_context.py] |
| MCP tools `search` / `read` / `edit` / `node` / `callers` / `callees` / `impact` / `usages` / `explore` | repo HEAD [CITED: src/atelier/gateway/adapters/mcp_server.py] | Host-facing contract | The host-facing tool contract is already consolidated and covered by gateway tests. [CITED: src/atelier/gateway/adapters/mcp_server.py; tests/gateway/test_mcp_tool_handlers.py; tests/gateway/test_p0_mcp_surfaces.py] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ripgrep` | 14.1.1 [CITED: bash audit (rg --version)] | Default search fallback backend for `search_read` | Use as the always-available grounding backend when optional large-repo backends are not routing. [CITED: src/atelier/core/capabilities/tool_supervision/search_read.py; src/atelier/core/capabilities/tool_supervision/smart_search.py] |
| Claude plugin hooks (`session_start.py`, `pre_tool_use.py`, `post_tool_use.py`) | repo HEAD [CITED: integrations/claude/plugin/hooks/session_start.py; integrations/claude/plugin/hooks/pre_tool_use.py; integrations/claude/plugin/hooks/post_tool_use.py] | Session warming, advisory grounding nudges, savings/ledger capture | Use only for host ergonomics and telemetry, not for new Phase 1 core behavior. [CITED: integrations/claude/plugin/hooks/hooks.json; integrations/claude/plugin/hooks/pre_tool_use.py] |
| `atelier.core.capabilities.session_optimizer` | repo HEAD [CITED: src/atelier/core/capabilities/session_optimizer.py] | Shared low-roundtrip guidance | Use for concise host guidance when improving ergonomics without adding hard workflow gates. [CITED: src/atelier/core/capabilities/session_optimizer.py; src/atelier/core/capabilities/plugin_runtime.py] |
| `docker` | 29.1.3 [CITED: bash audit (docker --version)] | Optional sidecar/runtime support | Relevant only if benchmark environments choose to enable optional backend services such as Zoekt sidecars. [CITED: docker-compose.yml; src/atelier/core/capabilities/tool_supervision/smart_search.py] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reusing `search_first` + `smart_search` | A brand-new MCP discovery tool | Reject this for Phase 1; it duplicates existing behavior and conflicts with the fixed brownfield-composition direction. [CITED: .planning/PROJECT.md; .planning/STATE.md; src/atelier/core/capabilities/grounded_loop/search_first.py] |
| Dedicated semantic escalation tools | Regex/grep-only follow-up | Reject this for Phase 1; grep cannot replace SCIP/tree-sitter-backed symbol and relationship answers. [CITED: src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/code_context/engine.py] |
| Advisory host nudges | Hard edit gates in hooks | Reject this for Phase 1; state explicitly defers hard grounded-edit gates to Phase 2, and `pre_tool_use.py` is non-blocking `ask`. [CITED: .planning/STATE.md; integrations/claude/plugin/hooks/pre_tool_use.py] |

**Installation:**
```bash
# No new packages are required for Phase 1.
# Reuse the existing Atelier runtime, MCP surface, and plugin/hook stack.
```

**Version verification:** Runtime prerequisites needed for this phase are present in this environment: `uv 0.11.7`, `Python 3.13.3` via `uv run`, `ripgrep 14.1.1`, `node v24.12.0`, `npm 11.6.2`, and `docker 29.1.3`. [CITED: bash audit (uv --version; uv run python --version; rg --version; node --version; npm --version; docker --version)]

## Package Legitimacy Audit

Not applicable for this phase because the recommended implementation composes existing in-repo capabilities and does not add new external packages. [CITED: .planning/PROJECT.md; src/atelier/core/capabilities/grounded_loop/search_first.py]

## Architecture Patterns

### System Architecture Diagram

```text
User prompt / host action
        |
        v
Claude host / MCP client
        |
        v
MCP tool contract (`search`, `read`, `edit`, code-intel wrappers)
        |
        +---- `search` -> `smart_search`
        |                  |
        |                  +--> optional backend routing (Zoekt) or `search_read`
        |                  +--> lexical + semantic + graph ranking
        |                  +--> ranked matches + visible provenance/backend
        |
        +---- follow-up handoff -> `read` / `context` / `explore`
        |                           |
        |                           +--> semantic file memory / context reuse / code-intel engine
        |
        +---- `edit` -> batch/rich edit + post-edit hooks + ledger diff capture
        |
        +---- plugin hooks -> session warm + advisory nudge + savings/telemetry
```

The intended flow is: search grounds the task first, then the same session escalates into exact semantic answers, then grouped edits happen with existing post-edit and ledger plumbing still attached. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/gateway/adapters/mcp_server.py; integrations/claude/plugin/hooks/hooks.json]

### Recommended Project Structure
```text
src/atelier/core/capabilities/grounded_loop/   # Search-first orchestration glue
src/atelier/core/capabilities/tool_supervision/ # ranked search, search_read, batched edit, shell policy
src/atelier/core/capabilities/code_context/     # semantic escalation engine
src/atelier/gateway/adapters/                   # MCP dispatch only
integrations/claude/plugin/hooks/               # advisory ergonomics + session capture
tests/core/capabilities/grounded_loop/          # search-first behavior locks
tests/gateway/                                  # MCP contract and host-surface locks
```

### Likely Change Surfaces

| Surface | Why it is the right change point | Change expectation |
|--------|-----------------------------------|-------------------|
| `src/atelier/core/capabilities/grounded_loop/search_first.py` | This is the Phase 1 orchestration shim already tested as the search-first wrapper. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; tests/core/capabilities/grounded_loop/test_search_first.py] | Primary place for composition tweaks. |
| `src/atelier/core/capabilities/tool_supervision/smart_search.py` | Ranking, backend selection, cache behavior, and repo-map mode live here. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] | Adjust only if grounding quality or provenance needs tuning. |
| `src/atelier/gateway/adapters/mcp_server.py` | Tool schemas/descriptions and thin dispatch live here. [CITED: src/atelier/gateway/adapters/mcp_server.py] | Limit to contract wording, exposure, or metadata plumbing; avoid new business logic. |
| `src/atelier/core/capabilities/code_context/engine.py` | Seed-file prioritization and semantic escalation quality live here. [CITED: src/atelier/core/capabilities/code_context/engine.py; tests/core/test_code_context.py] | Touch only if grounded search results must bias semantic follow-up better. |
| `integrations/claude/plugin/hooks/pre_tool_use.py` and `session_start.py` | Advisory grounding nudges and session warm behavior live here. [CITED: integrations/claude/plugin/hooks/pre_tool_use.py; integrations/claude/plugin/hooks/session_start.py] | Use only for ergonomic nudges; keep Phase 1 non-blocking. |
| `docs/agent-os/modes/code.md` and source docs that generate plugin agent files | Host guidance is sourced here, while `integrations/claude/plugin/agents/code.md` is generated. [CITED: docs/agent-os/modes/code.md; integrations/claude/plugin/agents/code.md; CLAUDE.md] | Edit sources, then regenerate; never patch generated agent files directly. |
| `tests/core/capabilities/grounded_loop/test_search_first.py`, `tests/gateway/test_p0_mcp_surfaces.py`, `tests/gateway/test_mcp_tool_handlers.py`, `tests/core/test_code_context.py` | These tests already lock the key Phase 1 behavior. [CITED: tests/core/capabilities/grounded_loop/test_search_first.py; tests/gateway/test_p0_mcp_surfaces.py; tests/gateway/test_mcp_tool_handlers.py; tests/core/test_code_context.py] | Update/add coverage alongside any behavior change. |

### Pattern 1: Search-first discovery envelope
**What:** Use `search_first` as the Phase 1 composition layer so grounded discovery always returns ranked matches plus explicit next-step affordances. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; tests/core/capabilities/grounded_loop/test_search_first.py]

**When to use:** Default path for file/path/match discovery when the user has not already grounded an exact symbol or file. [CITED: .planning/ROADMAP.md; src/atelier/core/capabilities/grounded_loop/search_first.py]

**Example:**
```python
# Source: src/atelier/core/capabilities/grounded_loop/search_first.py
payload = smart_search(
    query=query,
    path=path,
    mode="chunks",
    max_files=max_files,
    max_chars_per_file=max_chars_per_file,
    include_outline=include_outline,
    budget_tokens=budget_tokens,
)
```

### Pattern 2: Preserve semantic escalation as dedicated tools
**What:** Keep `node`, `callers`, `callees`, `impact`, `usages`, and `explore` as explicit, discoverable MCP tools over `CodeContextEngine`. [CITED: src/atelier/gateway/adapters/mcp_server.py]

**When to use:** Immediately after search has grounded likely files/symbols and the user needs exact symbol source, blast radius, or grouped relationships. [CITED: src/atelier/gateway/adapters/mcp_server.py; tests/core/test_code_context.py]

**Example:**
```python
# Source: src/atelier/gateway/adapters/mcp_server.py
@mcp_tool(name="explore")
def tool_explore(query: str, seed_files: list[str] | None = None, max_files: int = 8) -> dict[str, Any]:
    return _tool_symbols_alias_handler(
        {"op": "explore", "query": query, "seed_files": seed_files, "max_files": max_files}
    )
```

### Pattern 3: Advisory host ergonomics only
**What:** Use plugin hooks and session optimizer guidance to encourage grounding and batching without adding Phase 2-style hard workflow gates. [CITED: integrations/claude/plugin/hooks/pre_tool_use.py; integrations/claude/plugin/hooks/hooks.json; src/atelier/core/capabilities/session_optimizer.py]

**When to use:** Host UX prompts, session-start guidance, and low-roundtrip nudges. [CITED: integrations/claude/plugin/hooks/session_start.py; src/atelier/core/capabilities/plugin_runtime.py]

**Example:**
```python
# Source: integrations/claude/plugin/hooks/pre_tool_use.py
msg = (
    f"Atelier: `{target}` is in a risky domain ... Ground the change with `search` or `read`, "
    "call `context` with your current goal if you need repo memory, then batch related edits in one edit call."
)
print(json.dumps({"decision": "ask", "reason": msg}))
```

### Anti-Patterns to Avoid
- **New gateway-side discovery brain:** Do not add ranking or orchestration logic to `mcp_server.py`; tests already lock that grounded seed-file routing belongs in core/engine. [CITED: CLAUDE.md; tests/gateway/test_mcp_tool_handlers.py]
- **Search-only simplification:** Do not collapse `node`/`callers`/`impact`/`explore` into plain ranked snippets; that would regress one of Atelier's strongest differentiators. [CITED: .planning/PROJECT.md; src/atelier/gateway/adapters/mcp_server.py; src/atelier/core/capabilities/code_context/engine.py]
- **Phase-2 enforcement in Phase 1:** Do not convert advisory hook nudges into hard edit gates yet. [CITED: .planning/STATE.md; integrations/claude/plugin/hooks/pre_tool_use.py]
- **Editing generated agent files directly:** `integrations/claude/plugin/agents/code.md` is a generated distribution artifact. [CITED: integrations/claude/plugin/agents/code.md; CLAUDE.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Default grounded discovery | A new overlapping search MCP tool | `search_first` + `tool_smart_search` + explicit `grep` fallback | Existing code already composes ranked discovery, provenance, and handoffs. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/gateway/adapters/mcp_server.py] |
| Semantic repo understanding | Regex chains over grep output | `CodeContextEngine` via `node`/`callers`/`callees`/`usages`/`impact`/`explore` | Existing engine already provides symbol- and relationship-aware answers with token budgets and grounded `seed_files`. [CITED: src/atelier/core/capabilities/code_context/engine.py; tests/core/test_code_context.py] |
| Batched multi-file editing | Custom host-side edit loops | `edit` rich/batch descriptors | Existing handler already supports grouped edits, optional post-edit hooks, diff capture, and `calls_saved`. [CITED: src/atelier/gateway/adapters/mcp_server.py] |
| Search result caching/provenance | Ad hoc per-tool caches | Existing `smart_search` / `search_read` caches | Existing caches are already keyed to workspace/file fingerprints and surfaced through metadata. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] |
| Host bootstrap/nudge wiring | New one-off plugin codepath | Existing plugin hooks + `plugin_runtime` + `session_optimizer` | Existing host integration already applies session-start files, emits telemetry, and stays fail-open. [CITED: integrations/claude/plugin/hooks/hooks.json; integrations/claude/plugin/hooks/session_start.py; src/atelier/core/capabilities/plugin_runtime.py; src/atelier/core/capabilities/session_optimizer.py] |

**Key insight:** Phase 1 wins by tightening composition and discoverability around existing strengths, not by replacing those strengths with a simpler but shallower tool stack. [CITED: .planning/PROJECT.md; .planning/STATE.md]

## Common Pitfalls

### Pitfall 1: Hiding semantic escalation behind the search default
**What goes wrong:** Search becomes a dead-end snippet viewer, so users lose the cheap path into exact symbol, caller, usage, and impact answers. [CITED: .planning/ROADMAP.md; src/atelier/gateway/adapters/mcp_server.py]
**Why it happens:** Teams simplify discovery but forget that Atelier's advantage is preserved code-intel depth, not search alone. [CITED: .planning/PROJECT.md; .planning/REQUIREMENTS.md]
**How to avoid:** Keep explicit follow-ups in `search_first` and keep dedicated code-intel tools top-level and visible. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/gateway/adapters/mcp_server.py]
**Warning signs:** Search results stop carrying `explore`/`context` handoffs, or docs/tool descriptions stop mentioning semantic follow-up tools. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/gateway/adapters/mcp_server.py]

### Pitfall 2: Re-implementing ranking logic in the gateway
**What goes wrong:** `mcp_server.py` starts owning ranking heuristics, making the phase harder to maintain and violating the repo's layering rule. [CITED: CLAUDE.md]
**Why it happens:** The MCP tool surface is tempting because it is user-visible, but the repo explicitly keeps capability logic in `core`. [CITED: CLAUDE.md]
**How to avoid:** Change ranking in `smart_search` or `CodeContextEngine`, and keep gateway behavior as argument/schema/metadata plumbing only. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/code_context/engine.py; src/atelier/gateway/adapters/mcp_server.py]
**Warning signs:** New tests need to mock gateway ranking behavior instead of asserting pass-through to core. [CITED: tests/gateway/test_mcp_tool_handlers.py]

### Pitfall 3: Turning Phase 1 ergonomics into hard enforcement
**What goes wrong:** Users get blocked in the host loop before Atelier has the Phase 2 workflow kernel and grounded-edit gates. [CITED: .planning/ROADMAP.md; .planning/STATE.md]
**Why it happens:** Grounding nudges look similar to enforcement, but the current hook is intentionally `ask`/non-blocking. [CITED: integrations/claude/plugin/hooks/pre_tool_use.py]
**How to avoid:** Keep Phase 1 hook changes advisory and defer hard gates to Phase 2 work. [CITED: .planning/STATE.md; integrations/claude/plugin/hooks/pre_tool_use.py]
**Warning signs:** Hook decisions change from `ask` to blocking behavior or begin rejecting normal edits. [CITED: integrations/claude/plugin/hooks/pre_tool_use.py]

### Pitfall 4: Losing explicit grep and shell escape hatches
**What goes wrong:** Search-first feels magical until a regex/path-filter/build command is needed, then tool ergonomics degrade and solved-rate drops. [CITED: src/atelier/gateway/adapters/mcp_server.py; docs/agent-os/modes/code.md]
**Why it happens:** Ranked search and semantic tools solve many cases, but not regex/glob search or build/test/package-manager commands. [CITED: src/atelier/gateway/adapters/mcp_server.py; docs/agent-os/modes/code.md]
**How to avoid:** Keep `grep` explicit for regex/glob work and keep `shell` for commands with no Atelier equivalent. [CITED: src/atelier/gateway/adapters/mcp_server.py; docs/agent-os/modes/code.md]
**Warning signs:** Search tool descriptions stop directing users to `grep`, or shell begins duplicating search/read work instead of only covering missing equivalents. [CITED: src/atelier/gateway/adapters/mcp_server.py]

### Pitfall 5: Editing generated Claude agent artifacts
**What goes wrong:** Host ergonomics appear fixed locally, then get overwritten on the next regeneration/install step. [CITED: CLAUDE.md; integrations/claude/plugin/agents/code.md]
**Why it happens:** `integrations/claude/plugin/agents/code.md` is generated from docs sources. [CITED: integrations/claude/plugin/agents/code.md; CLAUDE.md]
**How to avoid:** Edit `docs/agent-os/...` sources, regenerate, then reinstall the plugin if plugin files changed. [CITED: CLAUDE.md; docs/agent-os/modes/code.md]
**Warning signs:** Changes are made directly under generated agent artifacts without matching source changes. [CITED: integrations/claude/plugin/agents/code.md; CLAUDE.md]

## Code Examples

Verified patterns from repository sources:

### Search-first handoff payload
```python
# Source: src/atelier/core/capabilities/grounded_loop/search_first.py
return {
    "discovery": {"tool": "search", "mode": "chunks"},
    "handoff": {
        "read": {"tool": "read"},
        "context": _context_follow_up(task=task, files=match_paths, mode="symbols"),
        "memory": _context_follow_up(task=task, files=match_paths, mode="procedures"),
        "explore": {"tool": "explore", "query": query, "seed_files": match_paths},
    },
}
```

### Grounded seed-files stay in core ranking
```python
# Source: tests/gateway/test_mcp_tool_handlers.py
fake_engine.tool_search.assert_called_once_with(
    "OrderService",
    limit=20,
    mode="auto",
    intent="auto",
    kind=None,
    language=None,
    seed_files=["src/orders.py"],
    snippet="none",
    snippet_lines=8,
    file_glob=None,
    scope="repo",
    budget_tokens=220,
)
```

### Advisory grounding nudge, not a hard gate
```python
# Source: integrations/claude/plugin/hooks/pre_tool_use.py
if not target or not _is_risky(target):
    print(json.dumps({"decision": "allow"}))
    return 0

print(json.dumps({"decision": "ask", "reason": msg}))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| User manually picks among overlapping discovery tools | Search-first ranked discovery with explicit `grep` fallback and explicit semantic follow-ups | Phase 1 roadmap shape documented on 2026-06-02. [CITED: .planning/ROADMAP.md; tests/core/capabilities/grounded_loop/test_search_first.py] | Lower discovery roundtrips without hiding precision tools. [CITED: .planning/REQUIREMENTS.md] |
| Gateway owns more orchestration | Core owns ranking and code-intel; gateway stays thin | Locked in current repo guidance and tests. [CITED: CLAUDE.md; tests/gateway/test_mcp_tool_handlers.py] | Less architectural drift and lower regression risk. [CITED: CLAUDE.md] |
| Native host file tools are primary | Generated Claude code persona disallows native Read/Edit/Write/Grep/Glob and docs tell Claude to prefer Atelier MCP tools | Current generated/plugin docs state. [CITED: integrations/claude/plugin/agents/code.md; docs/agent-os/modes/code.md; docs/agent-os/host-overrides/claude.md] | Better host/tool ergonomics only if Atelier surfaces remain complete and obvious. [CITED: docs/agent-os/modes/code.md] |

**Deprecated/outdated:**
- Editing generated Claude agent artifacts directly is outdated; source docs plus regeneration are the current path. [CITED: CLAUDE.md; integrations/claude/plugin/agents/code.md]
- Treating host-level hard routing/enforcement as Phase 1 scope is outdated for this roadmap; routing enforcement is deferred to later phases. [CITED: .planning/ROADMAP.md; .planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Benchmark runs should standardize on the ripgrep-backed search baseline unless optional backend routing is explicitly controlled as a benchmark condition. | Open Questions | Benchmark comparisons could become noisy or unfair across environments. |

## Open Questions

1. **Should benchmark runs for Phase 1 assume ripgrep-only discovery, or require optional large-repo backend routing consistency?**
   - What we know: `smart_search` can route to an optional backend and otherwise falls back to `search_read`/ripgrep, and this environment has Docker available. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; bash audit (docker --version)]
   - What's unclear: Whether benchmark comparisons will standardize on fallback search behavior or include optional backend acceleration. [ASSUMED]
   - Recommendation: Plan Phase 1 implementation against the ripgrep-backed baseline, and treat optional backend enablement as an explicitly controlled benchmark condition rather than implicit ambient state. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | Required repo command path | ✓ | 0.11.7 [CITED: bash audit (uv --version)] | — |
| Python via `uv run` | Runtime/tests/tooling | ✓ | 3.13.3 [CITED: bash audit (uv run python --version)] | — |
| `ripgrep` | `search_read` fallback backend | ✓ | 14.1.1 [CITED: bash audit (rg --version)] | None; this is the default search backend. |
| `node` | Existing frontend/tooling and some host install paths | ✓ | v24.12.0 [CITED: bash audit (node --version)] | — |
| `npm` | Existing frontend/plugin install paths | ✓ | 11.6.2 [CITED: bash audit (npm --version)] | — |
| `docker` | Optional sidecars/backends | ✓ | 29.1.3 [CITED: bash audit (docker --version)] | Phase 1 core loop can run without sidecars. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py] |

**Missing dependencies with no fallback:**
- None identified for the Phase 1 composition pass. [CITED: bash audit (uv/rg/node/npm/docker checks)]

**Missing dependencies with fallback:**
- Optional large-repo backend routing is non-blocking because `smart_search` falls back to `search_read`/ripgrep. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no [CITED: .planning/ROADMAP.md] | Not a Phase 1 concern; no auth changes are in scope. [CITED: .planning/ROADMAP.md] |
| V3 Session Management | no [CITED: .planning/ROADMAP.md] | Session hooks exist, but Phase 1 does not change auth/session policy. [CITED: integrations/claude/plugin/hooks/session_start.py; .planning/ROADMAP.md] |
| V4 Access Control | no [CITED: .planning/ROADMAP.md] | No new authorization boundary is introduced in this phase. [CITED: .planning/ROADMAP.md] |
| V5 Input Validation | yes [CITED: .planning/config.json; src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] | `smart_search` and `search_read` reject shell metacharacters/unsafe args; MCP tool schemas constrain inputs. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py; src/atelier/gateway/adapters/mcp_server.py] |
| V6 Cryptography | no [CITED: .planning/ROADMAP.md] | No crypto feature is added in this phase. [CITED: .planning/ROADMAP.md] |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Shell injection through search queries/paths | Tampering | `smart_search` and `search_read` reject shell metacharacters and leading-dash abuse before invoking search backends. [CITED: src/atelier/core/capabilities/tool_supervision/smart_search.py; src/atelier/core/capabilities/tool_supervision/search_read.py] |
| Destructive shell commands in fallback execution | Tampering | Shell policy blocks direct shell interpreters, `rm -rf`, `git reset --hard`, and `git clean -fd`, and rewrites `cat`/`rg`/`grep` to Atelier tools. [CITED: src/atelier/core/capabilities/tool_supervision/bash_exec.py; src/atelier/gateway/adapters/mcp_server.py] |
| Risky ungrounded edits in host UX | Tampering | Current Claude pre-tool hook issues advisory grounding prompts instead of silent allow for risky paths. [CITED: integrations/claude/plugin/hooks/pre_tool_use.py] |
| Silent provenance loss in discovery | Repudiation | `search_first` and `search` preserve backend/mode/provenance metadata, and tests assert those surfaces stay visible. [CITED: src/atelier/core/capabilities/grounded_loop/search_first.py; src/atelier/gateway/adapters/mcp_server.py; tests/gateway/test_p0_mcp_surfaces.py] |

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` - product target, brownfield constraint, benchmark-first framing.
- `.planning/REQUIREMENTS.md` - Phase 1 requirement set and out-of-scope lines.
- `.planning/ROADMAP.md` - Phase 1 goal, success criteria, and dependency boundary.
- `.planning/STATE.md` - Phase 1 implementation decisions, especially core-owned search orchestration and advisory-only host nudges.
- `.planning/phases/01-grounded-terminal-loop-mvp/01-CONTEXT.md` - locked direction and deferred items.
- `CLAUDE.md` - architecture invariants, generated-file policy, and command constraints.
- `src/atelier/core/capabilities/grounded_loop/search_first.py` - current Phase 1 composition shim.
- `src/atelier/core/capabilities/tool_supervision/smart_search.py` - ranked discovery, backend routing, fallback, and cache behavior.
- `src/atelier/core/capabilities/tool_supervision/search_read.py` - ripgrep-backed grounding fallback.
- `src/atelier/core/capabilities/code_context/engine.py` - semantic escalation, `seed_files` prioritization, and explore/context search behavior.
- `src/atelier/gateway/adapters/mcp_server.py` - public MCP contract for search/read/edit/code-intel/shell.
- `integrations/claude/plugin/hooks/hooks.json` - Claude hook wiring.
- `integrations/claude/plugin/hooks/session_start.py` - session warm/bootstrap behavior.
- `integrations/claude/plugin/hooks/pre_tool_use.py` - advisory grounding nudge behavior.
- `integrations/claude/plugin/hooks/post_tool_use.py` - diff capture into the run ledger.
- `src/atelier/core/capabilities/plugin_runtime.py` and `src/atelier/core/capabilities/session_optimizer.py` - generated guidance/bootstrap path.
- `docs/agent-os/modes/code.md` and `docs/agent-os/host-overrides/claude.md` - current host/tool ergonomics guidance.
- `integrations/claude/plugin/agents/code.md` - generated Claude code persona artifact and native tool disallow list.
- `tests/core/capabilities/grounded_loop/test_search_first.py` - search-first behavior lock.
- `tests/gateway/test_p0_mcp_surfaces.py` - MCP surface contract lock.
- `tests/gateway/test_mcp_tool_handlers.py` - gateway pass-through and grounded seed-file behavior lock.
- `tests/core/test_code_context.py` - code-intel prioritization and explore behavior lock.

### Secondary (MEDIUM confidence)
- `bash audit (uv --version; uv run python --version; rg --version; node --version; npm --version; docker --version)` - local environment availability only.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - The recommended stack is almost entirely existing repo code paths covered by tests and repo guidance. [CITED: source list above]
- Architecture: HIGH - Layer ownership and thin-gateway constraints are explicit in `CLAUDE.md`, code layout, and gateway tests. [CITED: CLAUDE.md; tests/gateway/test_mcp_tool_handlers.py]
- Pitfalls: MEDIUM - The failure modes are strongly implied by repo decisions/tests, but benchmark impact remains partially predictive until Phase 4 evidence exists. [CITED: .planning/STATE.md; .planning/ROADMAP.md; tests/core/capabilities/grounded_loop/test_search_first.py]

**Research date:** 2026-06-02
**Valid until:** 2026-07-02
