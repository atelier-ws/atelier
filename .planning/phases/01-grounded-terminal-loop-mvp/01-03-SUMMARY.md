---
phase: 01-grounded-terminal-loop-mvp
plan: 03
subsystem: infra
tags: [hooks, bash, claude, ergonomics, batching]
requires:
  - phase: 01-01
    provides: search-first grounding contract and follow-up expectations
provides:
  - search-first shell rewrites for plain discovery habits
  - soft Claude hook nudges for grounded multi-file edits and batching
affects: [phase-1, execution-kernel, host-integration]
tech-stack:
  added: []
  patterns: [soft guidance only, search-first host rewrites]
key-files:
  created:
    - tests/core/test_bash_exec_grounded_loop.py
    - tests/integrations/test_claude_grounded_loop_hooks.py
  modified:
    - src/atelier/core/capabilities/tool_supervision/bash_exec.py
    - integrations/claude/plugin/hooks/pre_tool_use.py
    - integrations/claude/plugin/hooks/user_prompt.py
key-decisions:
  - "Rewrite plain `rg` discovery habits to ranked `search`, but keep explicit regex-style usage on `grep`."
  - "Phase 1 host nudges stay advisory; hard grounded-edit gates remain deferred to Phase 2."
patterns-established:
  - "Hook nudges should add compact context pressure and grounded batching advice without blocking normal work."
requirements-completed: [GRND-03]
duration: 1min
completed: 2026-06-03
---

# Phase 1 Plan 03: Add low-roundtrip ergonomics and batching nudges without regressing existing smart context Summary

**Plain rg habits now steer toward Search-first grounding, while Claude hooks give soft multi-file batching nudges alongside existing compact-pressure warnings**

## Performance

- **Duration:** 1 min
- **Started:** 2026-06-03T00:33:01+02:00
- **Completed:** 2026-06-03T00:34:15+02:00
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Rewrote plain `rg` discovery commands toward ranked `search` while preserving `grep` for explicit pattern-search flags.
- Updated risky-edit hook guidance to recommend search/read/context grounding plus batched edits without blocking low-risk work.
- Added multi-file user-prompt nudges that coexist with existing compact warnings.

## Task Commits

1. **Task 1: Add failing regressions for soft grounded-loop ergonomics** - `abb986c` (test)
2. **Task 2: Align shell rewrites and Claude hooks with the Search-first loop** - `7d2a50b` (feat)

## Files Created/Modified
- `src/atelier/core/capabilities/tool_supervision/bash_exec.py` - rewrites plain `rg` into search-first grounding
- `integrations/claude/plugin/hooks/pre_tool_use.py` - risky-edit grounding and batching nudge
- `integrations/claude/plugin/hooks/user_prompt.py` - multi-file edit batching nudge that preserves compact warnings
- `tests/core/test_bash_exec_grounded_loop.py` - shell rewrite regressions
- `tests/integrations/test_claude_grounded_loop_hooks.py` - hook guidance regressions

## Decisions Made
- Limited `rg -> search` rewrites to simple literal queries so explicit regex-style search still routes to `grep`.
- Kept hook changes advisory and deterministic to match the Phase 1 “soft guidance only” boundary.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `bash scripts/install_claude.sh` refreshes generated plugin agent files in the repo; those generated artifacts were reverted after reinstall so only source hook changes remained committed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Host and shell entry points now reinforce the same grounded workflow used by Search-first core and semantic escalation.
- Phase 2 can add explicit grounded edit gates on top of these soft nudges without undoing Phase 1 ergonomics.

## Self-Check: PASSED
- Verified files exist: `src/atelier/core/capabilities/tool_supervision/bash_exec.py`, `tests/integrations/test_claude_grounded_loop_hooks.py`
- Verified commits exist: `abb986c`, `7d2a50b`
