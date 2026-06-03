---
phase: 02-execution-kernel-mvp
plan: 03
subsystem: runtime
tags: [grounded-loop, benchmark-gating, mcp, claude-hooks]
requires:
  - phase: 02-execution-kernel-mvp
    provides: Workflow state, plan review, and task progress summaries through the existing trace/report surfaces.
provides:
  - Canonical grounded-edit evidence helpers stored in workspace `session_state.json`.
  - Benchmark-only MCP edit blocking keyed to prior read/search/code-intel evidence.
  - Benchmark-only Claude pre-tool hook enforcement reusing the same evidence rules.
affects: [phase-02-closeout, benchmarking, edit-safety, claude-plugin]
tech-stack:
  added: []
  patterns:
    - Persist bounded, session-scoped grounding evidence in the existing workspace state instead of a new sidecar store.
    - Reuse the existing MCP edit dispatch seam and Claude `pre_tool_use` hook instead of adding a parallel enforcement path.
    - Keep hard blocking scoped to explicit benchmark mode while normal flows remain fail-open.
key-files:
  created:
    - .planning/phases/02-execution-kernel-mvp/02-03-SUMMARY.md
    - src/atelier/core/capabilities/grounded_loop/grounding_evidence.py
    - tests/core/test_grounding_evidence.py
  modified:
    - src/atelier/core/capabilities/grounded_loop/__init__.py
    - src/atelier/gateway/adapters/mcp_server.py
    - integrations/claude/plugin/hooks/pre_tool_use.py
    - tests/gateway/test_edit_mcp_handler.py
    - tests/integrations/test_claude_grounded_loop_hooks.py
key-decisions:
  - "Scoped grounding evidence to the current session ID to avoid old reads authorizing later benchmark edits."
  - "Used exact canonical file-path matching, reusing the MCP edit target normalization path, instead of heuristic fuzzy matching."
  - "Activated the hard gate only when `ATELIER_BENCH_MODE` is explicitly present so normal non-benchmark flows stay unchanged."
patterns-established:
  - "Grounding evidence sources are explicit: read, grep, search, context(symbols), and code-intel tools."
  - "Claude benchmark enforcement runs before the dev-mode soft-risk nudge, so benchmark blocks win over advisory asks."
requirements-completed: [EXEC-05, INTL-03]
duration: 71min
completed: 2026-06-03
---

# Phase 2: Plan 03 Summary

**Benchmark-path edits now require matching grounding evidence through both the MCP edit seam and the Claude pre-tool hook, while normal non-benchmark flows still fail open.**

## Performance

- **Duration:** 71 min
- **Started:** 2026-06-03T06:55:53Z
- **Completed:** 2026-06-03T08:06:16Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- Added a canonical `grounding_evidence` helper module that normalizes target paths, records bounded session-scoped evidence, and matches explicit edit targets.
- Wired benchmark-only MCP edit blocking before `tool_smart_edit()` runs, with evidence gathered from read/search/code-intel results into the existing workspace `session_state.json`.
- Updated the Claude `pre_tool_use` hook to block risky benchmark edits until evidence exists, while preserving the previous soft dev-mode nudge outside benchmark mode.
- Added focused regression coverage for the pure evidence helper, benchmark-only MCP edit blocking/allowing, and benchmark-only Claude hook blocking/allowing.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing benchmark-path gating tests at the MCP and Claude seams** - `ad11370` (feat)
2. **Task 2: Record canonical grounding evidence and enforce the MCP benchmark edit gate** - `ad11370` (feat)
3. **Task 3: Reuse the same evidence rules in the Claude pre-edit hook** - `ad11370` (feat)

**Plan metadata:** `3672e15` (docs: plan phase 2)

## Files Created/Modified
- `src/atelier/core/capabilities/grounded_loop/grounding_evidence.py` - Adds canonical path normalization, session-scoped evidence recording, explicit evidence extraction, and exact target matching.
- `src/atelier/core/capabilities/grounded_loop/__init__.py` - Exports the new grounding-evidence helpers.
- `src/atelier/gateway/adapters/mcp_server.py` - Records grounding evidence from supported tools, writes workspace state atomically, and blocks benchmark edits before handler execution when evidence is missing.
- `integrations/claude/plugin/hooks/pre_tool_use.py` - Reuses the shared grounding-evidence helpers and benchmark-mode detection to block risky benchmark edits before the dev-mode advisory path.
- `tests/core/test_grounding_evidence.py` - Covers normalization, session scoping, bounded evidence retention, and search/code-intel target extraction.
- `tests/gateway/test_edit_mcp_handler.py` - Verifies blocked ungrounded benchmark edits, allowed grounded benchmark edits after `read`, and non-benchmark fail-open behavior.
- `tests/integrations/test_claude_grounded_loop_hooks.py` - Verifies blocked/allowed benchmark hook decisions and preserves the prior soft risky-path guidance outside benchmark mode.

## Decisions Made
- Used session-scoped evidence entries inside workspace `session_state.json` so evidence cannot leak across sessions in the same repo workspace.
- Reused the MCP edit target normalization path and exact target matching rather than adding fuzzy or parent-directory evidence rules.
- Chose explicit benchmark-mode env activation for the hard gate so the new enforcement does not silently change ordinary non-benchmark editing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Hook control flow] Ran benchmark blocking before the existing dev-mode soft-risk advisory**
- **Found during:** Task 3 (Reuse the same evidence rules in the Claude pre-edit hook)
- **Issue:** The hook originally returned `allow` for non-dev flows before it ever checked the new benchmark gate, so benchmark-mode risky edits were not blocked.
- **Fix:** Moved benchmark enforcement ahead of the `_is_dev_mode()` early return so benchmark blocks take precedence and dev-mode soft asks still work outside benchmark mode.
- **Files modified:** `integrations/claude/plugin/hooks/pre_tool_use.py`, `tests/integrations/test_claude_grounded_loop_hooks.py`
- **Verification:** Focused hook and full `02-03` verification suites passed after the change.
- **Committed in:** `ad11370`

**2. [Validation flow] Adjusted tests to treat “non-benchmark” as benchmark env absent rather than the repo-wide `bench-off` baseline arm**
- **Found during:** Task 1 (Add failing benchmark-path gating tests at the MCP and Claude seams)
- **Issue:** Setting `ATELIER_BENCH_MODE=off` triggered broader bench-off routing behavior unrelated to this plan’s grounded-edit gate, obscuring the intended fail-open check.
- **Fix:** Updated the non-benchmark regression to clear the benchmark env instead, which matches the plan’s requirement that ordinary flows remain unchanged when the gate is not explicitly active.
- **Files modified:** `tests/gateway/test_edit_mcp_handler.py`
- **Verification:** The non-benchmark edit regression now exercises only the grounded-edit gate boundary and passes alongside the benchmark-specific cases.
- **Committed in:** `ad11370`

---

**Total deviations:** 2 auto-fixed (hook control flow, validation flow)
**Impact on plan:** Both fixes tightened the implementation to the plan’s actual benchmark-only scope without widening behavior or adding new storage/enforcement paths.

## Issues Encountered
- The hook initially looked correct at the helper level, but a reproduction showed `main()` still returned `allow`; the real problem was the old dev-mode early return running before the new benchmark gate.
- The repository commit hook reformatted the changed Python files with Black, so the feature commit was retried after restaging the hook-formatted result.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
Phase `02-03` now enforces the benchmark-path grounded edit rule end-to-end through the existing MCP and Claude seams.
Phase 2 can be closed once the active roadmap/phase inventory is reconciled with any additional `02-04` / `02-05` planning artifacts already present in the working tree.

---
*Phase: 02-execution-kernel-mvp*
*Completed: 2026-06-03*
