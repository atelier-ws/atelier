# Phase 1: Grounded Terminal Loop MVP - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

As a terminal coding agent user, I want a grounded Search-first workflow with semantic escalation, so that I can solve repo tasks faster without losing precision.

Success criteria carried from ROADMAP.md:
1. User can use a Search-first default path for file/path/match discovery without manually picking among overlapping tools.
2. User can escalate grounded results into precise symbol, caller, usage, and impact answers in the same session.
3. User can batch related edits and follow-up reads while existing memory and code-intel strengths still work.

Requirements in scope:
- GRND-01
- GRND-02
- GRND-03
- INTL-01
- INTL-02

</domain>

<decisions>
## Implementation Decisions

### the agent's Discretion
All implementation choices are at the agent's discretion unless a genuine blocker appears. Optimize for the benchmark-first terminal coding agent target: Eval is the execution-discipline reference, Augment is the context-quality reference, and WOZ is the host/tool ergonomics reference.

### Fixed Direction
- Reuse existing Atelier strengths instead of rewriting the stack.
- Prioritize research and exploration before implementation.
- Prefer correct, non-bloated implementation over heavy validation/tightening loops.
- Keep the top-level host/tool experience simple while preserving Atelier's semantic code-intel depth.

</decisions>

<code_context>
## Existing Code Insights

Relevant existing strengths to preserve:
- Context and memory composition already exist.
- Dedicated code-intel surfaces already exist.
- Host-side tracing and enforcement already exist.

Initial codebase context should focus on:
- MCP/server tool surfaces for read/search/edit/memory/code-intel
- Host hook/tool-routing behavior
- Existing context/memory entry points that must remain intact

</code_context>

<specifics>
## Specific Ideas

- Compose a Search-first default path over existing surfaces instead of replacing code-intel with generic search.
- Keep semantic escalation obvious and cheap once Search has grounded the task.
- Add ergonomic nudges/batching only where they reduce roundtrips without hiding capability.

</specifics>

<deferred>
## Deferred Ideas

- Full host-level routing changes
- Minified read/edit path
- Benchmark gate implementation

</deferred>
