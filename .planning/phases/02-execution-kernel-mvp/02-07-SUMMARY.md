---
phase: 02-execution-kernel-mvp
plan: 07
subsystem: read-minify
tags: [context-compression, read-path, minify, mcp]
requires:
  - phase: 02-execution-kernel-mvp
    provides: Canonical reader/exact split expectations plus Phase 2 owned workflow/default/solver surfaces.
provides:
  - Reader-only structural whitespace minification for a safe language allowlist.
  - Exact-read bypass for `expand=True` and explicit `range` reads on the MCP read path.
  - Per-read `MinificationDelta` telemetry surfaced only on the metadata path.
affects: [phase-3-routing, context-compression, mcp-read, benchmark-cost]
tech-stack:
  added: []
  patterns:
    - Use a positive allowlist for aggressive minification instead of treating all non-significant languages as safe.
    - Keep the default read path approximate/reader-profile and treat `expand=True` plus explicit `range` as the exact-read signal on the current MCP API.
    - Surface minification telemetry only behind `include_meta` while always preserving internal saved-token accounting.
key-files:
  created:
    - .planning/phases/02-execution-kernel-mvp/02-07-SUMMARY.md
    - tests/core/test_structural_minify.py
    - tests/gateway/test_mcp_read_minify.py
  modified:
    - src/atelier/core/capabilities/context_compression/minify.py
    - src/atelier/gateway/adapters/mcp_server.py
key-decisions:
  - "Aggressive intra-line whitespace collapse is allowlisted to languages the line scanner can treat safely; whitespace-significant and unknown languages keep the conservative transform."
  - "The current MCP read API has no explicit profile flag, so default reads remain the reader-profile path while `expand=True` and explicit `range` are the exact-read escape hatches."
  - "Minification deltas are surfaced only with `include_meta=True` so the default read payload stays stable."
patterns-established:
  - "Quoted spans remain byte-preserved during aggressive collapse, including multiline backtick spans."
  - "Exact reads bypass aggressive minification entirely; writer/edit flows continue to see byte-exact content."
requirements-completed: [EXEC-14, GRND-03, INTL-03]
duration: 18min
completed: 2026-06-03
---

# Phase 2: Plan 07 Summary

**Atelier now gets the read-side token win from structural whitespace minification on the default reader path, while explicit exact reads stay byte-exact and the savings remain attributable through the existing minification telemetry.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-06-03T09:35:00Z
- **Completed:** 2026-06-03T09:53:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added `test_structural_minify.py` to lock the aggressive reader-side transform contract: safe-language whitespace collapse, conservative behavior for whitespace-significant/unknown languages, purity, and quoted-span preservation.
- Added `test_mcp_read_minify.py` to pin the MCP read split: default reads may minify, while `expand=True` and explicit `range` remain exact and skip minification telemetry.
- Extended `minify_source()` with an allowlisted intra-line whitespace collapse that preserves leading indentation and quoted spans while still keeping the existing conservative transform for all other languages.
- Updated the MCP read handler so only the default reader path applies the aggressive transform, while exact reads bypass it and metadata responses can surface a `minification_delta`.

## Files Created/Modified

- `src/atelier/core/capabilities/context_compression/minify.py` - Adds the allowlisted structural whitespace collapse on top of the conservative transform.
- `src/atelier/gateway/adapters/mcp_server.py` - Restricts aggressive minification to the default reader path and surfaces `minification_delta` under `include_meta`.
- `tests/core/test_structural_minify.py` - Covers safe-language collapse, conservative-path preservation, and quoted-span/purity guarantees.
- `tests/gateway/test_mcp_read_minify.py` - Covers default-reader minify vs exact-read bypass behavior.

## Decisions Made

- Used a positive allowlist for aggressive minification after the design critique highlighted that a blacklist would wrongly mutate languages with heredocs, regex literals, or richer quoting forms.
- Interpreted the existing API shape instead of adding a new read-profile argument: the default call is the reader path, while `expand=True` or an explicit `range` is the existing exact-read signal.
- Kept `minification_delta` behind `include_meta=True` so existing read consumers keep their default payload shape.

## Deviations from Plan

### Auto-fixed Issues

**1. [Safety model] Switched from a blacklist to a positive safe-language allowlist**
- **Found during:** Pre-implementation design critique
- **Issue:** Treating every non-whitespace-significant language as safe would have risked corrupting bash heredocs, JS regex literals, SQL dollar quotes, and other unhandled forms.
- **Fix:** Aggressive collapse now only applies to a strict allowlist, while whitespace-significant and unknown languages stay on the conservative transform.
- **Files modified:** `src/atelier/core/capabilities/context_compression/minify.py`, `tests/core/test_structural_minify.py`

**2. [Exact-read boundary] Limited the aggressive transform to the default reader path**
- **Found during:** Pre-implementation design critique
- **Issue:** The existing MCP read contract already treats `expand=True` and explicit `range` reads as exact, so minifying those paths would have violated the tool contract.
- **Fix:** The MCP handler now bypasses aggressive minification for exact reads and only reports the `MinificationDelta` on minified default reads.
- **Files modified:** `src/atelier/gateway/adapters/mcp_server.py`, `tests/gateway/test_mcp_read_minify.py`

## Issues Encountered

- The initial inline-collapse helper omitted its final return, which the new structural-minify tests caught immediately; the bug was fixed before broader validation.

## User Setup Required

None.

## Next Phase Readiness

Phase 2 is now complete. Phase 3 can focus on provider/model routing and cache-affinity execution without having to reopen the owned workflow/default/solver/read-cost substrate.

---
*Phase: 02-execution-kernel-mvp*
*Completed: 2026-06-03*
