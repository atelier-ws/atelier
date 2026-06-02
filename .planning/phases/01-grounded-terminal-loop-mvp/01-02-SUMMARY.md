---
phase: 01-grounded-terminal-loop-mvp
plan: 02
subsystem: api
tags: [code-intel, search, mcp, semantic-escalation]
requires:
  - phase: 01-01
    provides: search-first grounding payloads and follow-up context hooks
provides:
  - grounded seed-file routing into code-intel search
  - visible search mode and provenance for semantic follow-up answers
affects: [phase-1, execution-kernel, code-intel]
tech-stack:
  added: []
  patterns: [thin gateway dispatch, engine-owned grounded reranking]
key-files:
  created: []
  modified:
    - src/atelier/gateway/adapters/mcp_server.py
    - src/atelier/core/capabilities/code_context/engine.py
    - tests/gateway/test_p0_mcp_surfaces.py
    - tests/gateway/test_mcp_tool_handlers.py
    - tests/core/test_code_context.py
key-decisions:
  - "Grounded seed files should bias code-intel ranking in CodeContextEngine while the gateway only forwards context."
  - "Search responses must keep mode and provenance visible so semantic escalation remains discoverable."
patterns-established:
  - "MCP search wrappers forward grounded context, but ranking lives in the engine."
requirements-completed: [GRND-02, INTL-02]
duration: 10min
completed: 2026-06-03
---

# Phase 1 Plan 02: Preserve code-intel escalation paths inside the simplified terminal loop Summary

**Grounded search now flows into seed-aware code-intel results while keeping search mode and provenance visible for exact follow-up tools**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-03T00:21:43+02:00
- **Completed:** 2026-06-03T00:31:45+02:00
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Added seed-file-aware ranking to `CodeContextEngine.tool_search`.
- Forwarded grounded `seed_files` from MCP search into the engine without adding gateway-owned ranking logic.
- Preserved `mode`, `view`, `provenance`, and `cache_hit` on search responses so semantic escalation stays legible after grounding.

## Task Commits

1. **Task 1: Capture the semantic-escalation contract with failing MCP and engine tests** - `d13cdd4` (test)
2. **Task 2: Wire Search-first grounding into the existing code-intel escalation lane** - `f650386` (feat)

## Files Created/Modified
- `src/atelier/core/capabilities/code_context/engine.py` - accepts `seed_files` and prioritizes grounded matches before packing results
- `src/atelier/gateway/adapters/mcp_server.py` - forwards grounded seed files, advertises semantic follow-up tools, and keeps search response metadata visible
- `tests/gateway/test_p0_mcp_surfaces.py` - public search-contract regressions
- `tests/gateway/test_mcp_tool_handlers.py` - thin-dispatch regressions for grounded search handoff
- `tests/core/test_code_context.py` - engine regression for grounded seed-file prioritization

## Decisions Made
- Preserved the dedicated `node` / `callers` / `callees` / `usages` / `impact` / `explore` surfaces rather than hiding them behind a multiplexer again.
- Kept grounded reranking stable and minimal by only promoting already-grounded files, leaving the engine’s existing ordering otherwise intact.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored stripped search metadata needed for semantic follow-up**
- **Found during:** Task 2
- **Issue:** MCP search responses were stripping `mode`, `view`, `provenance`, and cache state, making grounded semantic escalation opaque and breaking existing search regressions.
- **Fix:** Kept those fields on `search` responses while leaving other code-op stripping unchanged.
- **Files modified:** `src/atelier/gateway/adapters/mcp_server.py`
- **Verification:** Focused MCP search regression suite passed.
- **Committed in:** `f650386`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The fix was necessary to preserve discoverable semantic escalation with the simplified loop.

## Issues Encountered
- Full-file MCP suites still contain pre-existing unrelated failures logged in `deferred-items.md`; the grounded semantic regression set passes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Search-first results now hand off grounded file context directly into semantic tooling.
- Phase 1 ergonomics work can now align shell and hook nudges with the same search-first path.

## Self-Check: PASSED
- Verified files exist: `src/atelier/core/capabilities/code_context/engine.py`, `src/atelier/gateway/adapters/mcp_server.py`
- Verified commits exist: `d13cdd4`, `f650386`
