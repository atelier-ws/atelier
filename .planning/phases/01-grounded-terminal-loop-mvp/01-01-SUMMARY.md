---
phase: 01-grounded-terminal-loop-mvp
plan: 01
subsystem: infra
tags: [search, grounding, memory, mcp, smart-search]
requires: []
provides:
  - search-first core orchestration over existing smart_search and search_read surfaces
  - stable read/context/explore handoff metadata for grounded follow-up work
affects: [phase-1, semantic-escalation, host-nudges]
tech-stack:
  added: []
  patterns: [thin core orchestration, search-first handoffs]
key-files:
  created:
    - src/atelier/core/capabilities/grounded_loop/__init__.py
    - src/atelier/core/capabilities/grounded_loop/search_first.py
  modified:
    - src/atelier/core/capabilities/tool_supervision/smart_search.py
    - src/atelier/core/capabilities/tool_supervision/search_read.py
    - tests/core/capabilities/grounded_loop/test_search_first.py
    - tests/core/test_smart_search_baseline.py
key-decisions:
  - "Keep Search-first orchestration in core and compose existing smart_search/search_read primitives instead of adding a new gateway surface."
patterns-established:
  - "Search-first responses should carry explicit read/context/explore follow-up metadata."
requirements-completed: [GRND-01, INTL-01]
duration: 2min
completed: 2026-06-03
---

# Phase 1 Plan 01: Compose Search-first grounding over existing read/search/edit/memory surfaces Summary

**Search-first core orchestration that returns ranked matches plus explicit read, context, memory, and explore handoffs**

## Performance

- **Duration:** 2 min
- **Started:** 2026-06-03T00:15:13+02:00
- **Completed:** 2026-06-03T00:17:14+02:00
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Added a reusable `grounded_loop.search_first` capability in core.
- Preserved existing smart-search and search-read execution paths instead of duplicating search logic.
- Exposed stable handoff metadata for exact reads, symbol context, memory recall, and explore follow-ups.

## Task Commits

1. **Task 1: Lock the Search-first happy path with failing core tests** - `1ec706f` (test)
2. **Task 2: Implement thin Search-first composition in core capabilities** - `bc61439` (feat)

## Files Created/Modified
- `src/atelier/core/capabilities/grounded_loop/search_first.py` - thin Search-first orchestrator over existing core primitives
- `src/atelier/core/capabilities/grounded_loop/__init__.py` - capability export
- `src/atelier/core/capabilities/tool_supervision/smart_search.py` - carries match paths and token metadata through ranked search results
- `src/atelier/core/capabilities/tool_supervision/search_read.py` - exposes stable `match_paths` in serialized fallback payloads
- `tests/core/capabilities/grounded_loop/test_search_first.py` - happy-path and primitive-reuse regressions
- `tests/core/test_smart_search_baseline.py` - baseline roundtrip-savings assertion for batched grounded discovery

## Decisions Made
- Kept the new Search-first policy inside `core/capabilities/` to preserve the `gateway -> core -> infra` boundary.
- Reused `smart_search` as the single discovery primitive and expressed follow-up steps as metadata instead of adding a new public MCP tool.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `make lint` and `make typecheck` surfaced pre-existing unrelated failures logged in `deferred-items.md`; targeted plan verification passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Search-first grounding now returns explicit follow-up hooks that Plan 02 can wire into semantic escalation.
- No blockers for the remaining Phase 1 plans.

## Self-Check: PASSED
- Verified files exist: `src/atelier/core/capabilities/grounded_loop/search_first.py`, `tests/core/capabilities/grounded_loop/test_search_first.py`
- Verified commits exist: `1ec706f`, `bc61439`
