# Phase 2: Execution Kernel MVP - Context

**Gathered:** 2026-06-03
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

As a terminal coding agent user, I want an owned workflow runner with explicit state, canonical defaults, grounded edit discipline, and benchmark solver retry semantics, so that multi-step tasks stay coherent from plan through execution and can recover from harness feedback.

Success criteria carried from ROADMAP.md:
1. User can move through explicit explore, plan, execute, and review workflow states in one session.
2. User can approve or revise a plan before execution starts.
3. User can resume execution with current-task state and prior task outputs preserved.
4. User can only apply benchmark-path edits after the relevant code has been grounded by read/search/code-intel steps.
5. User can run an Atelier-owned workflow DAG with persistent/forkable step context, safe scheduling, and per-step telemetry.
6. User can inspect and regenerate default agent, skill, workflow, prompt, MCP, and benchmark-profile definitions from one canonical source.
7. User can run a benchmark solver profile headlessly, retry from harness feedback, and emit artifact-backed JSON/stream-JSON outputs.

Requirements in scope:
- EXEC-01
- EXEC-02
- EXEC-03
- EXEC-04
- EXEC-05
- EXEC-06
- EXEC-07
- EXEC-08
- EXEC-09
- EXEC-10
- EXEC-11
- EXEC-12
- DFLT-01
- DFLT-02
- DFLT-03
- DFLT-04
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
- Do not stop at advisory workflow state. Eval parity requires an Atelier-owned runner that executes workflow DAG steps, carries persistent/forkable context, schedules safe tool work, and records per-step telemetry.
- Treat defaults as a product runtime contract, not packaging leftovers. Eval ships named agent definitions, prompts, workflows, settings, and non-overwriting bootstrap behavior; Atelier needs the same canonical-definition discipline across its host-specific generated surfaces.
- Treat the benchmark solver as a product runtime, not only a prompt. It needs canonical solver rules, harness-feedback retry, cleanup discipline, and headless artifacts.
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
- a thin owned workflow runner that reuses current gateway/core/infra primitives instead of leaving execution ownership with host hooks alone
- a canonical default-definition registry that generates or verifies current Claude, Codex, OpenCode, Antigravity, shared skill, workflow, MCP, and benchmark-runtime surfaces
- benchmark solver execution paths that can run outside an interactive host loop and preserve raw artifacts for later proof

</code_context>

<specifics>
## Specific Ideas

- Introduce a typed session workflow object rather than scattering more state across prompts.
- Preserve a thin gateway and core-owned behavior.
- Make plan review and progress visible through existing tracing/reporting surfaces.
- Scope grounded edit gates to the benchmark execution path first.
- Add an owned workflow step schema with `agent`, `tool`, and `shell` step kinds, `next_steps`, `execute_if`, `fork_from`, `json_output`, output files, timeout, and silent/stream flags.
- Persist per-step context so review can fork from plan and execution can reuse the accepted/revised plan without re-reading everything.
- Add a safe scheduler: read/search/code-intel work may batch; writes, shell mutations, and interactive decisions serialize.
- Add canonical defaults for these roles: `code/general`, `explore`, `plan`, `execute`, `review`, `research`, and `solve`.
- Canonical default metadata must include name, description, model/provider tier where owned, effort, tool allow/deny policy, max turns/tokens, prompt body, workflow usage, and host-surface projection rules.
- Add a benchmark solve profile with explicit install/build/probe command rules, artifact-first work, no repeated failed commands, cleanup expectations, and bounded retry from harness feedback.
- Add headless owned-run output formats that report step outputs, tokens, cache use, cost, duration, and raw artifact paths.

</specifics>

<deferred>
## Deferred Ideas

- Broader provider routing changes (Phase 3)
- Benchmark protocol and proof surfaces (Phase 4)
- Any cloud-style Augment parity beyond what directly improves the terminal loop
- Whiteboard/visual planning parity from Eval unless evidence shows it improves terminal-bench-style solved-rate

</deferred>
