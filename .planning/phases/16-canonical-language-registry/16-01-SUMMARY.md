---
phase: 16-canonical-language-registry
plan: 01
subsystem: infra
tags: [code-intel, tree-sitter, scip, language-registry, refactor]

# Dependency graph
requires: []
provides:
  - "src/atelier/infra/code_intel/languages.py — canonical language registry (single source of truth for language identity)"
  - "Language frozen dataclass, LANGUAGES table, EXTENSION_TO_LANGUAGE, ALL_LANGUAGES, language_for_path, language_by_name"
  - "Drift-guard test asserting every treesitter_ast._LANG_CONFIG key resolves via the registry"
affects: [16-02, code-intel-consumers, scip-phase-19]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stdlib-only leaf registry module (frozen dataclass + derived lookup dicts + __all__), mirroring scip/binaries.py"

key-files:
  created:
    - src/atelier/infra/code_intel/languages.py
    - tests/infra/code_intel/test_languages.py
  modified: []

key-decisions:
  - "Shell extensions (.sh/.bash/.zsh) canonicalize to `bash` at the data layer (DLS-LANG-03), resolving the shell/bash drift bug"
  - "scip_indexer seeded only for python/typescript/javascript; full SCIP table deferred to Phase 19"
  - "Unknown extensions resolve to None at the registry boundary; callers map None->'text'"
  - "Did NOT add tests/infra/code_intel/__init__.py — pytest already collects this package (sibling scip/ has none and collects fine)"

patterns-established:
  - "Canonical registry pattern: frozen Language records, comprehension-derived EXTENSION_TO_LANGUAGE/_BY_NAME, pure lookup functions, no auto-detection"
  - "Cross-surface drift-guard test: parametrize over _LANG_CONFIG keys, assert each resolves via language_by_name"

requirements-completed: [DLS-LANG-01, DLS-LANG-02]

# Metrics
duration: 18min
completed: 2026-05-29
---

# Phase 16 Plan 01: Canonical Language Registry Summary

**Stdlib-only `languages.py` registry unifying the duplicated extension→language maps into a frozen `Language` table, canonicalizing shell→bash and seeding SCIP indexer metadata for python/typescript/javascript.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-29T10:38:00Z
- **Completed:** 2026-05-29T10:56:00Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments
- Created `src/atelier/infra/code_intel/languages.py` as the single source of truth for language identity (extensions, parser names, SCIP indexer metadata).
- Seeded `LANGUAGES` as the union of `capability._language_for` and `search_read._LANG_MAP` extension coverage — no extension dropped.
- Canonicalized shell extensions to `bash` at the data layer (DLS-LANG-03), fixing the shell/bash drift bug.
- Added 55 parametrized unit tests covering DLS-LANG-01/02/03 plus the DLS-LANG-04 drift-guard invariant over `treesitter_ast._LANG_CONFIG`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create canonical language registry module** — `acd6775` (feat)
2. **Task 2: Add registry unit tests and drift-guard invariant** — `5c2851e` (test)

## Files Created/Modified
- `src/atelier/infra/code_intel/languages.py` — Canonical registry: `Language` frozen dataclass, `LANGUAGES` table, derived `EXTENSION_TO_LANGUAGE`/`ALL_LANGUAGES`, `language_for_path`, `language_by_name`. stdlib-only (`dataclasses`, `pathlib`); no `atelier.core` imports (Pitfall 1).
- `tests/infra/code_intel/test_languages.py` — 55 tests: public-surface types (DLS-LANG-01), legacy extension→canonical-name parametrization (DLS-LANG-02), None fallback, shell→bash boundary (DLS-LANG-03), `_LANG_CONFIG` drift guard (DLS-LANG-04). `-k extensions` and `-k canonical` selectors each match ≥1 test.

## Decisions Made
- **No `tests/infra/code_intel/__init__.py` created:** the plan said to add it only if pytest fails to collect. Collection already works (verified via `pytest --co` on the sibling `scip/` package which also lacks `__init__.py`), so it was omitted to avoid unnecessary files.
- **`# type: ignore[misc]` on the frozen-mutation test:** the frozen-dataclass assignment test (`sample.name = "mutated"` inside `pytest.raises(FrozenInstanceError)`) is flagged by mypy `--strict` as a read-only-property error when `languages.py` is in the same invocation (as in `make typecheck`). The ignore is required for the project-wide typecheck to pass.

## Deviations from Plan

None — plan executed exactly as written. (The two decisions above are plan-sanctioned choices, not deviations: the `__init__.py` was explicitly conditional, and the type:ignore is a minimal correctness fix for the test that mypy strict requires.)

## Issues Encountered
- **Pre-existing, out-of-scope typecheck failures:** `make typecheck` reports 4 errors in `src/atelier/core/runtime/engine.py` (`context_reuse.models` missing `PhaseCacheStats`/`PhasePlan`/`PhaseResult`/`RunMode`). This file is an unrelated uncommitted user change in the working tree (`git status` shows `M src/atelier/core/runtime/engine.py`) and was NOT touched by this plan. Per the scope boundary, these were left alone. The new `languages.py` and `test_languages.py` both pass `mypy --strict` cleanly.

## Validation Commands Run
- `uv run python -c "import atelier.infra.code_intel.languages"` → import-clean (no cycle).
- Task 1 acceptance assertions (shell→bash, csharp, unknown→None, scip_indexer) → `ok`.
- `uv run pytest tests/infra/code_intel/test_languages.py -q` → 55 passed.
- `uv run pytest ... -k extensions` → 38 passed; `-k canonical` → 39 passed.
- `uv run ruff check` (both files) → All checks passed.
- `uv run mypy --strict src/atelier/infra/code_intel/languages.py tests/infra/code_intel/test_languages.py` → no issues.

## User Setup Required
None — internal refactor, no external service configuration.

## Next Phase Readiness
- Registry leaf module + tests are complete and green. Plan 02 can now migrate the four consuming surfaces (`capability.py`, `search_read.py`, `treesitter_ast.py`, `scip/binaries.py`) to delegate to this registry.
- No blockers introduced by this plan.

---
*Phase: 16-canonical-language-registry*
*Completed: 2026-05-29*

## Self-Check: PASSED

- FOUND: src/atelier/infra/code_intel/languages.py
- FOUND: tests/infra/code_intel/test_languages.py
- FOUND: .planning/phases/16-canonical-language-registry/16-01-SUMMARY.md
- FOUND commit: acd6775 (Task 1, feat)
- FOUND commit: 5c2851e (Task 2, test)
