---
phase: 02-execution-kernel-mvp
plan: 05
subsystem: defaults
tags: [defaults-registry, renderer, bootstrap, benchmark-solver]
requires:
  - phase: 02-execution-kernel-mvp
    provides: Owned workflow runner, benchmark edit gating, and current host-generated mode surfaces.
provides:
  - Canonical registry for owned roles, prompts, workflows, benchmark profiles, MCP templates, and host projections.
  - Registry-backed renderer/static checks for shared skills and generated host agent surfaces.
  - Non-overwriting defaults bootstrap with deterministic created/skipped/changed/invalid receipts.
affects: [02-06, host-surfaces, benchmark-solver, owned-runtime]
tech-stack:
  added: []
  patterns:
    - Keep host-facing prompt bodies sourced from `docs/agent-os/modes/*.md` while owned runtime metadata lives in `default_definitions.py`.
    - Model runtime-only roles explicitly instead of leaking them into generated host bundles.
    - Treat defaults bootstrap as append-only/non-destructive: classify divergent local files as `changed` rather than overwriting them.
key-files:
  created:
    - .planning/phases/02-execution-kernel-mvp/02-05-SUMMARY.md
    - src/atelier/core/capabilities/default_definitions.py
    - src/atelier/core/capabilities/workflow_defaults.py
    - tests/core/test_default_definitions.py
  modified:
    - scripts/render_mode_surfaces.py
    - scripts/build_host_skills.sh
    - tests/gateway/test_agent_cli_install_artifacts.py
    - tests/gateway/test_claude_plugin_static_surface.py
key-decisions:
  - "The registry owns stable role/workflow/profile metadata, but host-facing prompt bodies still come from the existing Atelier mode docs instead of duplicating large prompts in Python."
  - "The `general` role is runtime-only and intentionally has no host projection, so the existing seven surfaced roles stay unchanged."
  - "Bootstrap writes one manifest plus per-role/prompt/workflow/profile/template files and reports divergent local files as `changed` without overwriting them."
patterns-established:
  - "Owned workflows share one `owned-stem-system` prompt and pivot through per-phase user prompts with explicit fork intent (`plan` from `explore`, `review`/`refine` from `plan`, solver retry from `review`)."
  - "Reviewer defaults now live in canonical metadata: no mutating actions, first-hand evidence required, one JSON verdict block, default `NEEDS_FIX` on ambiguity."
requirements-completed: [EXEC-12, EXEC-13, DFLT-01, DFLT-02, DFLT-03, DFLT-04]
duration: 33min
completed: 2026-06-03
---

# Phase 2: Plan 05 Summary

**Atelier now has one canonical default-definition registry for owned runtime roles, prompts, workflows, benchmark profiles, MCP templates, and host projections, and the existing generated surfaces are checked against it without introducing a second prompt source.**

## Performance

- **Duration:** 33 min
- **Started:** 2026-06-03T08:31:00Z
- **Completed:** 2026-06-03T09:04:00Z
- **Tasks:** 5
- **Files modified:** 8

## Accomplishments

- Added `default_definitions.py` with canonical role metadata for `code`, `general`, `explore`, `plan`, `execute`, `review`, `research`, and `solve`, including tool policies, model/effort/turn defaults, read hints, host projections, owned workflows, benchmark profiles, and MCP templates.
- Kept host-facing mode bodies sourced from `docs/agent-os/modes/*.md`, while adding owned-runtime prompt metadata such as the shared stem system prompt, phase pivot prompts, reviewer verdict contract, and solver retry prompt.
- Added `workflow_defaults.py` with non-overwriting bootstrap helpers that materialize manifest, role, prompt, workflow, benchmark-profile, and MCP-template defaults into a workspace-local `defaults/` tree.
- Rewrote `render_mode_surfaces.py` to render shared skills plus Claude/OpenCode/Antigravity agent surfaces from the canonical registry rather than from hardcoded per-host maps in the script itself.
- Updated `build_host_skills.sh` so the bundle set comes from the canonical surfaced-role registry and uses repo-standard `uv run python` calls.
- Added focused contract tests for registry completeness, owned workflow/solver defaults, host projection mapping, renderer drift detection, and bootstrap receipts.

## Files Created/Modified

- `src/atelier/core/capabilities/default_definitions.py` - Canonical registry for owned roles, prompts, workflows, host projections, MCP templates, and benchmark solver defaults.
- `src/atelier/core/capabilities/workflow_defaults.py` - Default bootstrap helpers and receipt models for safe workspace-local installation.
- `scripts/render_mode_surfaces.py` - Registry-backed generation/check logic for shared skills and host agent files.
- `scripts/build_host_skills.sh` - Shared-skill bundle generation driven by canonical surfaced roles.
- `tests/core/test_default_definitions.py` - Registry, projection, owned workflow, solver-profile, and bootstrap coverage.
- `tests/gateway/test_agent_cli_install_artifacts.py` - Stable bundle and render drift checks tied back to canonical surfaced roles.
- `tests/gateway/test_claude_plugin_static_surface.py` - Canonical role-set and wording-safety checks for Claude plugin surfaces.

## Decisions Made

- Avoided making `core` depend on repo docs at import time: the registry stores stable metadata and prompt source references, while render/check flows resolve markdown bodies from the repository only when asked.
- Kept the current seven host-surfaced roles stable and modeled `general` as runtime-only so the owned workflow runner can use it later without changing distribution surfaces today.
- Used per-file bootstrap artifacts instead of one monolithic defaults blob so future releases can add new defaults without overwriting user-local files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Runtime coupling] Split stable runtime metadata from repo-only mode parsing**
- **Found during:** Pre-implementation design critique
- **Issue:** A registry that eagerly parsed `docs/agent-os/modes/*.md` inside runtime code would become fragile outside a repo checkout.
- **Fix:** The registry now stores stable metadata plus prompt-source references, and only render/check/bootstrap paths resolve mode-doc bodies from the repository.
- **Files modified:** `src/atelier/core/capabilities/default_definitions.py`, `scripts/render_mode_surfaces.py`, `tests/core/test_default_definitions.py`

**2. [Bootstrap evolution] Replaced the single-file defaults idea with a manifest plus per-default artifacts**
- **Found during:** Pre-implementation design critique
- **Issue:** One `default_registry.json` would block future additive defaults because non-overwrite behavior would freeze the whole payload after first install.
- **Fix:** Bootstrap now writes a manifest plus separate role/prompt/workflow/profile/template files and reports divergent local files as `changed`.
- **Files modified:** `src/atelier/core/capabilities/workflow_defaults.py`, `tests/core/test_default_definitions.py`

## Issues Encountered

- The repository worktree already contained unrelated planning and generated-surface changes, so `02-05` was validated against focused tests and changed-file gates without assuming the worktree was otherwise clean.
- The new bootstrap manifest helper needed a follow-up mypy tightening so sorted index generation stayed fully typed.

## User Setup Required

None - defaults bootstrap is non-destructive and no external host CLIs are required for the focused validation suite.

## Next Phase Readiness

The owned runtime now has canonical solver-role, reviewer-contract, workflow, and retry-discipline defaults that `02-06` can consume directly instead of restating prompt/rule text in the solver runtime.

---
*Phase: 02-execution-kernel-mvp*
*Completed: 2026-06-03*
