---
phase: 02-execution-kernel-mvp
plan: 02
subsystem: runtime
tags: [workflow-progress, trace, session-stats, session-report]
requires:
  - phase: 02-execution-kernel-mvp
    provides: Explicit review workflow state persisted in the canonical workspace session state.
provides:
  - Durable workflow-state, plan-review, and task-progress summaries in the existing run ledger.
  - Structured trace-tool wiring for workflow/progress events without introducing a new workflow bus.
  - Session-stats and session-report summaries for workflow step, review decision, and task progress.
affects: [02-03, reporting, tracing, statusline]
tech-stack:
  added: []
  patterns:
    - Reuse RunLedger as the only durable workflow/progress reporting store.
    - Normalize workflow event payloads at the MCP trace seam before they reach ledger/report consumers.
    - Reuse existing session_stats and session_report surfaces instead of adding a parallel report path.
key-files:
  created:
    - .planning/phases/02-execution-kernel-mvp/02-02-SUMMARY.md
  modified:
    - src/atelier/infra/runtime/run_ledger.py
    - src/atelier/gateway/adapters/mcp_server.py
    - src/atelier/core/capabilities/plugin_runtime.py
    - src/atelier/infra/runtime/session_report.py
    - tests/infra/test_run_ledger.py
    - tests/infra/test_session_report.py
    - tests/gateway/test_mcp_tool_handlers.py
    - tests/gateway/test_plugin_runtime_hooks.py
key-decisions:
  - "Stored latest workflow state, plan review, and task progress directly on RunLedger snapshots instead of reconstructing them from free-form notes."
  - "Kept `trace` receipts stable and mirrored structured workflow events into the ledger rather than extending the Trace model."
  - "Extended existing session stats and text report surfaces with workflow/progress summaries instead of adding new files or APIs."
patterns-established:
  - "Workflow event payloads are normalized to recognized shapes (`workflow_state`, `plan_review`, `task_progress`) before persistence."
  - "Session stats emit a compact workflow-progress notice only when a new workflow/progress payload is supplied."
requirements-completed: [EXEC-02, EXEC-04, INTL-03]
duration: 23min
completed: 2026-06-03
---

# Phase 2: Plan 02 Summary

**Plan review decisions and task progress now flow through the existing trace, ledger, session-stats, and session-report surfaces as one consistent workflow/progress summary.**

## Performance

- **Duration:** 23 min
- **Started:** 2026-06-03T06:33:00Z
- **Completed:** 2026-06-03T06:55:46Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Added structured `workflow_state`, `plan_review`, and `task_progress` summaries to `RunLedger`, including persist/load round-tripping.
- Updated the MCP `trace` tool to normalize recognized workflow/progress payloads into the ledger while preserving the compact `trace_id`/`event_recorded` receipt.
- Exposed the latest workflow step, review decision, and task counts through existing session-stats and session-report renderers.
- Locked the slice with focused regression coverage for review decisions (`approve`, `revise`, `rerun`) plus task-progress trace events.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing workflow/progress coverage across trace, stats, and report seams** - `a6c53e3` (feat)
2. **Task 2: Mirror structured workflow events into ledger, status, and report surfaces** - `a6c53e3` (feat)

**Plan metadata:** `3672e15` (docs: plan phase 2)

## Files Created/Modified
- `src/atelier/infra/runtime/run_ledger.py` - Adds structured workflow/progress summary fields plus a helper recording path that persists across snapshot/load.
- `src/atelier/gateway/adapters/mcp_server.py` - Normalizes recognized workflow event payloads in `trace` and mirrors them into the ledger without changing the trace receipt contract.
- `src/atelier/core/capabilities/plugin_runtime.py` - Folds workflow/progress payloads into `session_stats` and emits compact workflow progress notices.
- `src/atelier/infra/runtime/session_report.py` - Surfaces workflow step, review decision, and task counts in the report dataclass and text renderer.
- `tests/infra/test_run_ledger.py` - Covers structured workflow/progress persistence through snapshot and load.
- `tests/infra/test_session_report.py` - Verifies workflow/progress summaries render in session reports.
- `tests/gateway/test_mcp_tool_handlers.py` - Exercises `trace` for review decisions and task progress while preserving the compact receipt.
- `tests/gateway/test_plugin_runtime_hooks.py` - Verifies session stats and progress output carry the latest workflow/progress state.

## Decisions Made
- Reused `RunLedger` snapshot fields as the durable workflow/progress source of truth instead of mining raw note events on every read.
- Kept workflow event data out of the strict `Trace` model and stored it at the ledger seam, which avoided widening the trace schema for reporting-only concerns.
- Used existing session progress/status output plumbing so the new slice stays visible anywhere that already reads `session_stats`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Trace schema compatibility] Kept structured workflow data in the ledger path instead of the Trace payload**
- **Found during:** Task 2 (Mirror structured workflow events into the ledger and reporting surfaces)
- **Issue:** Adding `event_type` and `event_payload` directly to the `Trace` payload violated the strict Pydantic schema for `Trace`.
- **Fix:** Preserved structured workflow/progress data only in the normalized ledger recording path while leaving the trace receipt unchanged.
- **Files modified:** `src/atelier/gateway/adapters/mcp_server.py`, `tests/gateway/test_mcp_tool_handlers.py`
- **Verification:** Focused trace, ledger, session-stats, and session-report tests passed after the adjustment.
- **Committed in:** `a6c53e3`

---

**Total deviations:** 1 auto-fixed (trace schema compatibility)
**Impact on plan:** No scope change. The fix kept the design aligned with the original "reuse existing seams" constraint.

## Issues Encountered
- The repository commit hook reformatted the changed Python files with Black, so the feature commit was retried after restaging the hook-formatted result.
- Repo-wide `make lint` and `make typecheck` still hit the known unrelated baseline failures (`benchmarks/eval/run.py`, `scripts/extract_flow.py`, duplicate `benchmarks` mypy module), so this slice was validated on the touched files plus focused workflow/progress tests.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
Phase `02-02` now provides the visibility surfaces needed for benchmark-mode grounded edit enforcement.
Plan `02-03` can build benchmark-only edit gating on top of the persisted workflow/review/task-progress state without introducing any new reporting surfaces.

---
*Phase: 02-execution-kernel-mvp*
*Completed: 2026-06-03*
