---
phase: 01-grounded-terminal-loop-mvp
plan: 02
subsystem: infra
tags: [code-intel, seed-files, glob, deleted-history]
requires: []
provides:
  - Seed-aware semantic escalation keeps grounded files prioritized inside CodeContextEngine.
  - Workspace, snippet, and deleted-history search views preserve the fields needed for precise follow-up.
affects: [02-execution-kernel-mvp, code-context, semantic-escalation]
tech-stack:
  added: []
  patterns:
    - Use path-aware glob matching in code-intel surfaces instead of raw fnmatch semantics.
    - Preserve scope-specific search fields rather than collapsing live, workspace, and deleted-history views into one generic shape.
key-files:
  created:
    - .planning/phases/01-grounded-terminal-loop-mvp/01-02-SUMMARY.md
  modified:
    - src/atelier/core/capabilities/code_context/engine.py
    - src/atelier/gateway/adapters/mcp_server.py
key-decisions:
  - "Seeded semantic ranking remains owned by CodeContextEngine; the gateway only forwards context and shapes responses."
  - "File-glob filters must use slash-aware path matching so user globs behave predictably across repo search surfaces."
patterns-established:
  - "Code-intel search keeps scope-specific fields like repo tags, snippets, and deleted-history metadata when they are meaningful to follow-up work."
  - "repo_root overrides must be wired explicitly at the MCP boundary for temp-repo and workspace-scoped tests."
requirements-completed: [GRND-02, INTL-02]
duration: 58min
completed: 2026-06-02
---

# Phase 1: Plan 02 Summary

**Seed-aware semantic escalation now uses slash-aware glob matching and preserves workspace, snippet, and deleted-history fields needed for precise code-intel follow-up.**

## Performance

- **Duration:** 58 min
- **Started:** 2026-06-02T22:38:08Z
- **Completed:** 2026-06-02T23:36:31Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Fixed code-intel file-glob matching so patterns like `src/*.py` no longer overmatch nested paths.
- Restored `repo_root` support and scope-specific search payload shaping for workspace, snippet, and deleted-history operations.
- Revalidated that grounded `seed_files` stay a core-owned semantic-ranking input instead of becoming gateway-side logic.

## Task Commits

1. **Task 1: Add failing seeded-escalation regression tests** - existing coverage revalidated during the rerun closeout
2. **Task 2: Keep semantic escalation core-owned and budget-safe** - `c32192a` (fix)

**Plan metadata:** `c7592a2` (docs: rerun phase 1 planning)

## Files Created/Modified
- `src/atelier/core/capabilities/code_context/engine.py` - Uses slash-aware path matching for user-facing glob filters across search, usage, and relation views.
- `src/atelier/gateway/adapters/mcp_server.py` - Forwards `repo_root`, distinguishes deleted-history search kwargs, and preserves scope-specific target item fields.

## Decisions Made
- Kept seed ranking and grounded escalation behavior inside `CodeContextEngine` instead of pushing interpretation into the gateway.
- Preserved `repo_name`, `snippet`, and deleted-history metadata in target items because those fields are part of the user-visible follow-up contract for workspace and graveyard searches.

## Deviations from Plan

### Auto-fixed Issues

**1. [Path matching] Replaced raw fnmatch semantics with slash-aware glob matching**
- **Found during:** Task 2 (Keep semantic escalation core-owned and budget-safe)
- **Issue:** Raw `fnmatch` treated user globs too permissively and allowed nested-path matches that broke the Phase 1 search contract.
- **Fix:** Normalized paths through `PurePosixPath.match()` and reused the helper across code-intel search/filter entry points.
- **Files modified:** `src/atelier/core/capabilities/code_context/engine.py`
- **Verification:** Focused code-context and handler regressions covering glob behavior passed after the patch.
- **Committed in:** `c32192a`

**2. [Search shaping] Restored repo, snippet, and deleted-history fields in scoped search results**
- **Found during:** Task 2 (Keep semantic escalation core-owned and budget-safe)
- **Issue:** Workspace and snippet/deleted search payloads were dropping fields needed for precise follow-up and temp-repo routing tests.
- **Fix:** Wired `repo_root` through the MCP symbols/code entrypoint, distinguished deleted-history kwargs, and preserved scoped target item fields.
- **Files modified:** `src/atelier/gateway/adapters/mcp_server.py`
- **Verification:** Targeted handler subset for workspace, snippet, seed-files, and deleted-history search passed after the patch.
- **Committed in:** `c32192a`

---

**Total deviations:** 2 auto-fixed (path matching, scoped search shaping)
**Impact on plan:** All changes were direct correctness repairs that re-established the planned semantic-escalation contract without broadening scope.

## Issues Encountered
- The rerun surfaced two real regressions in code-intel behavior: permissive glob semantics and over-stripped scoped search payloads. Both were tightly coupled to Plan 02 and were fixed in the closeout patch.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
Grounded results can escalate into precise code-intel follow-up again without gateway-side reranking.
Phase 2 can rely on the current grounded loop as the stable substrate for explicit execution state and grounded edit discipline.

---
*Phase: 01-grounded-terminal-loop-mvp*
*Completed: 2026-06-02*
