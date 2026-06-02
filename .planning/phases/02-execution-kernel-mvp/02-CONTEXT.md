# Phase 2: Execution Kernel MVP - Context

**Gathered:** 2026-06-03
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

As a terminal coding agent user, I want explicit workflow state and grounded edit discipline, so that multi-step tasks stay coherent from plan through execution.

Success criteria carried from ROADMAP.md:
1. User can move through explicit explore, plan, execute, and review workflow states in one session.
2. User can approve or revise a plan before execution starts.
3. User can resume execution with current-task state and prior task outputs preserved.
4. User can only apply benchmark-path edits after the relevant code has been grounded by read/search/code-intel steps.

Requirements in scope:
- EXEC-01
- EXEC-02
- EXEC-03
- EXEC-04
- EXEC-05
- INTL-03

</domain>

<decisions>
## Implementation Decisions

### the agent's Discretion
All implementation choices are at the agent's discretion unless a genuine blocker appears. Optimize for the benchmark-first terminal coding agent target: Eval is the execution-discipline reference, Augment is the context-quality reference, and WOZ remains the ergonomics reference already established in Phase 1.

### Fixed Direction
- Reuse Atelier's existing runtime, tracing, and reporting foundations instead of inventing a parallel workflow engine.
- Build explicit workflow state and carry-forward outputs on top of the newly shipped Search-first path.
- Convert Phase 1's soft grounded-loop guidance into benchmark-path edit discipline without bloating normal flows.
- Prefer correct implementation over heavy verification loops.

</decisions>

<code_context>
## Existing Code Insights

Phase 1 established:
- Search-first core orchestration in `src/atelier/core/capabilities/grounded_loop/search_first.py`
- grounded seed-file routing into code-intel search
- soft shell and host nudges aligned with the grounded loop

Phase 2 should focus on:
- current workflow/autopilot/runtime state handling
- tracing/reporting surfaces that can expose plan/progress/workflow events
- benchmark-path edit gates that build on Phase 1 grounding signals instead of fighting them

</code_context>

<specifics>
## Specific Ideas

- Introduce a typed session workflow object rather than scattering more state across prompts.
- Preserve a thin gateway and core-owned behavior.
- Make plan review and progress visible through existing tracing/reporting surfaces.
- Scope grounded edit gates to the benchmark execution path first.

</specifics>

<deferred>
## Deferred Ideas

- Broader provider routing changes (Phase 3)
- Benchmark protocol and proof surfaces (Phase 4)
- Any cloud-style Augment parity beyond what directly improves the terminal loop

</deferred>
