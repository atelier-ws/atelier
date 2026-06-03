---
phase: 02-execution-kernel-mvp
plan: 04
subsystem: runtime
tags: [workflow-runner, workflow-schema, workflow-context, mcp]
requires:
  - phase: 02-execution-kernel-mvp
    provides: Explicit workflow state, report surfaces, and benchmark edit gating on top of existing session state.
provides:
  - Typed owned workflow schema with dependency validation across edges, template refs, and fork refs.
  - Persistent runner context stored under canonical workflow session state.
  - Conservative owned DAG runner with step telemetry and a thin `workflow_run` MCP seam.
affects: [02-05, 02-06, reporting, benchmark-solver]
tech-stack:
  added: []
  patterns:
    - Keep workflow execution state under `session_state["workflow"]["runner"]` as the single owned-runner source of truth.
    - Derive workflow dependencies from `next_steps`, template references, and `fork_from` instead of trusting only explicit edges.
    - Parallelize only allowlisted read/search/code-intel tool waves and serialize agent/shell steps.
key-files:
  created:
    - .planning/phases/02-execution-kernel-mvp/02-04-SUMMARY.md
    - src/atelier/core/capabilities/workflow_schema.py
    - src/atelier/core/capabilities/workflow_context.py
    - src/atelier/core/capabilities/workflow_runner.py
    - tests/core/test_workflow_runner.py
    - tests/gateway/test_mcp_workflow_runner.py
  modified:
    - src/atelier/gateway/adapters/mcp_server.py
    - src/atelier/infra/runtime/run_ledger.py
key-decisions:
  - "Workflow DAG validation now treats template references and `fork_from` as real dependencies, not just `next_steps`."
  - "Per-step runner history is persisted separately in `RunLedger.workflow_step_events` while the existing workflow/task summaries stay aggregate."
  - "The MCP seam delegates to `_run_owned_workflow()` and keeps provider/model execution for agent steps deferred to later injected executors."
patterns-established:
  - "Workflow templates only allow full-value substitutions like `{{steps.step_id.output}}` and `{{steps.step_id.output_json.key}}`."
  - "Forked step context is copy-on-write from the source step result; canonical stored outputs remain immutable."
requirements-completed: [EXEC-06, EXEC-07, EXEC-08, EXEC-11, INTL-03]
duration: 24min
completed: 2026-06-03
---

# Phase 2: Plan 04 Summary

**Atelier now has an owned workflow DAG runner with validated step definitions, persistent runner state, conservative scheduling, per-step ledger telemetry, and a thin `workflow_run` MCP seam.**

## Performance

- **Duration:** 24 min
- **Started:** 2026-06-03T08:06:16Z
- **Completed:** 2026-06-03T08:30:28Z
- **Tasks:** 4
- **Files modified:** 8

## Accomplishments
- Added `workflow_schema.py` with typed step/workflow definitions, dependency derivation, and fast validation for invalid kinds, missing refs, and cycles.
- Added `workflow_context.py` with serializable `StepResult`, canonical runner state, minimal full-value template substitution, and copy-on-write `fork_from` context.
- Added `workflow_runner.py` with deterministic wave planning, conservative safe-tool batching, injected executors, and stop-on-failure semantics.
- Extended `RunLedger` with `workflow_step_events` so per-step start/done/fail history survives snapshot/load instead of being collapsed into only aggregate workflow summaries.
- Added a thin `workflow_run` MCP tool that delegates to `_run_owned_workflow()`, persists runner state under `session_state["workflow"]["runner"]`, and returns a compact run receipt.

## Task Commits

Each task was committed atomically:

1. **Task 1: Lock the owned workflow contract with failing tests** - `da0624a` (feat)
2. **Task 2: Implement typed workflow schema and persistent step context** - `da0624a` (feat)
3. **Task 3: Implement the core runner and safe scheduler** - `da0624a` (feat)
4. **Task 4: Add the thin MCP invocation seam** - `da0624a` (feat)

**Plan metadata:** `3672e15` (docs: plan phase 2)

## Files Created/Modified
- `src/atelier/core/capabilities/workflow_schema.py` - Defines workflow and step models, dependency extraction, safe-tool classification, and validation.
- `src/atelier/core/capabilities/workflow_context.py` - Defines persisted step results and minimal runner context rendering/fork helpers.
- `src/atelier/core/capabilities/workflow_runner.py` - Implements owned DAG execution, wave scheduling, injected executors, and stop-on-failure behavior.
- `src/atelier/gateway/adapters/mcp_server.py` - Adds default runner executors, `_run_owned_workflow()`, and the thin `workflow_run` MCP tool.
- `src/atelier/infra/runtime/run_ledger.py` - Persists `workflow_step_events` alongside aggregate workflow state/progress summaries.
- `tests/core/test_workflow_runner.py` - Covers schema validation, dependency-derived waves, copy-on-write forks, successful runner telemetry, and stop-on-failure behavior.
- `tests/gateway/test_mcp_workflow_runner.py` - Confirms the gateway seam delegates to the owned runner and preserves the compact receipt contract.

## Decisions Made
- Kept the template system intentionally small and strict to avoid turning this phase into a general workflow DSL.
- Stored owned-runner state only under `session_state["workflow"]["runner"]`, while leaving top-level workflow fields as compatibility summaries for existing consumers.
- Deferred default agent-step execution to injected executors instead of smuggling provider/model logic into the gateway before Phase 3.

## Deviations from Plan

### Auto-fixed Issues

**1. [Telemetry shape] Added explicit `workflow_step_events` history instead of overloading the existing aggregate workflow summaries**
- **Found during:** Task 3 (Implement the core runner and safe scheduler)
- **Issue:** Existing `RunLedger.record_workflow_event()` only retained the latest aggregate `workflow_state` / `task_progress`, which was insufficient for per-step runner history.
- **Fix:** Added a separate `workflow_step_events` persistence surface while keeping the existing aggregate workflow/progress summaries unchanged.
- **Files modified:** `src/atelier/infra/runtime/run_ledger.py`, `src/atelier/core/capabilities/workflow_runner.py`, `tests/core/test_workflow_runner.py`
- **Verification:** Focused runner tests and the `02-04` verify suite passed with persisted start/done/fail step history.
- **Committed in:** `da0624a`

**2. [Dependency safety] Derived scheduling dependencies from template refs and `fork_from`, not only explicit `next_steps` edges**
- **Found during:** Design critique before implementation
- **Issue:** A scheduler that only trusted explicit DAG edges could run a step before its referenced inputs existed.
- **Fix:** Built dependency extraction from `next_steps`, template refs, and `fork_from` and validated the combined graph for missing refs and cycles before execution.
- **Files modified:** `src/atelier/core/capabilities/workflow_schema.py`, `src/atelier/core/capabilities/workflow_runner.py`, `tests/core/test_workflow_runner.py`
- **Verification:** The owned-workflow wave-planning regression passed with implicit template dependency coverage.
- **Committed in:** `da0624a`

---

**Total deviations:** 2 auto-fixed (telemetry shape, dependency safety)
**Impact on plan:** Both changes tightened correctness while preserving the planned thin gateway / conservative runner design.

## Issues Encountered
- The repo’s commit hook reformatted the new workflow files with Black, so the feature commit was retried after restaging the hook-formatted result.
- Strict typing needed a small follow-up pass in the new workflow modules before the changed-file mypy gate went green.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
The owned workflow substrate now exists for canonical defaults and benchmark solver profiles to target.
Phase `02-05` can define the canonical role/workflow/default registry without inventing a second workflow execution surface.

---
*Phase: 02-execution-kernel-mvp*
*Completed: 2026-06-03*
