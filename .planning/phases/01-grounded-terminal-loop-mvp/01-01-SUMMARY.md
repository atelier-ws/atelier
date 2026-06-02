---
phase: 01-grounded-terminal-loop-mvp
plan: 01
subsystem: gateway
tags: [search, grounded-loop, mcp, discoverability]
requires: []
provides:
  - Search-first MCP responses keep ranked-discovery metadata and explicit follow-up affordances visible.
  - Thin gateway shaping preserves the live search contract instead of hiding semantic escalation hints.
affects: [02-execution-kernel-mvp, grounded-loop, mcp-search]
tech-stack:
  added: []
  patterns:
    - Preserve discoverability metadata at the gateway boundary while keeping ranking logic in core.
    - Keep live-search wrapper contracts additive rather than special-casing follow-up tools.
key-files:
  created:
    - .planning/phases/01-grounded-terminal-loop-mvp/01-01-SUMMARY.md
  modified:
    - src/atelier/gateway/adapters/mcp_server.py
    - tests/gateway/test_p0_mcp_surfaces.py
key-decisions:
  - "Search-first rerun fixes stay in the thin MCP wrapper; ranked discovery remains core-owned."
  - "Live search continues to expose mode/provenance and default forwarding fields so semantic escalation stays discoverable."
patterns-established:
  - "Gateway search shaping may strip telemetry, but it must preserve user-visible routing and follow-up fields."
  - "Additive search extensions should honor the baseline live-search contract instead of redefining it."
requirements-completed: [GRND-01]
duration: 58min
completed: 2026-06-02
---

# Phase 1: Plan 01 Summary

**Search-first MCP responses now keep live discovery metadata and additive follow-up affordances visible without moving ranking logic out of core.**

## Performance

- **Duration:** 58 min
- **Started:** 2026-06-02T22:38:08Z
- **Completed:** 2026-06-02T23:36:31Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Restored the thin MCP search wrapper so live search keeps `mode`, `provenance`, and target item fields that Phase 1 users rely on for follow-up decisions.
- Preserved additive blame/search behavior by aligning the surface contract with the default live-search forwarding shape.
- Revalidated the Search-first grounding contract against the refreshed Phase 1 plan set.

## Task Commits

1. **Task 1: Lock the Search-first grounding contract with failing regression coverage** - existing coverage revalidated during the rerun closeout
2. **Task 2: Implement Search-first composition in core and keep MCP plumbing thin** - `c32192a` (fix)

**Plan metadata:** `c7592a2` (docs: rerun phase 1 planning)

## Files Created/Modified
- `src/atelier/gateway/adapters/mcp_server.py` - Preserves user-visible live-search metadata while still stripping internal context-waste fields.
- `tests/gateway/test_p0_mcp_surfaces.py` - Locks the additive blame/search contract to the stable live-search forwarding shape.

## Decisions Made
- Kept the rerun fix in the adapter layer instead of reworking `search_first` or `smart_search`, because the regression was in boundary shaping rather than ranking behavior.
- Treated `mode`, `provenance`, and target-view fields as part of the user-facing Search-first contract, not disposable telemetry.

## Deviations from Plan

### Auto-fixed Issues

**1. [Wrapper contract] Restored stripped Search-first response fields**
- **Found during:** Task 2 (Implement Search-first composition in core and keep MCP plumbing thin)
- **Issue:** The target-view search wrapper had drifted and was dropping live-search metadata and item fields that made semantic escalation discoverable.
- **Fix:** Adjusted gateway response shaping to preserve the live-search contract and updated the additive blame surface test to match that contract.
- **Files modified:** `src/atelier/gateway/adapters/mcp_server.py`, `tests/gateway/test_p0_mcp_surfaces.py`
- **Verification:** Focused Phase 1 MCP/search regression suite passed after the patch.
- **Committed in:** `c32192a`

---

**Total deviations:** 1 auto-fixed (wrapper contract drift)
**Impact on plan:** Correctness-only repair. No scope creep and no new gateway orchestration logic introduced.

## Issues Encountered
- The rerun exposed wrapper drift in the live search payload even though the original Phase 1 implementation already covered most of the plan. Fixing the boundary contract was enough to restore plan compliance.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
Phase 1 Search-first grounding is re-closed with the refreshed plan set and targeted rerun validation is green.
Phase 2 can start from the existing grounded loop without reworking the discovery contract.

---
*Phase: 01-grounded-terminal-loop-mvp*
*Completed: 2026-06-02*
