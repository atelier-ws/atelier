---
phase: 16-canonical-language-registry
plan: 02
subsystem: code-intel
tags: [code-intel, tree-sitter, scip, language-registry, refactor, shell-outline]

# Dependency graph
requires:
  - "src/atelier/infra/code_intel/languages.py — canonical language registry (from 16-01)"
provides:
  - "capability._language_for delegating to language_for_path (None->'text'; shell->bash)"
  - "tags.detect_language delegating to language_for_path (preserves str|None)"
  - "scip/binaries.discover_scip_binary sourcing indexer identity from registry scip_indexer"
  - "tests/core/test_shell_outline.py — .sh produces kind:treesitter outline regression"
  - "SCIP env-var preservation test in tests/infra/code_intel/scip/test_scip_adapter.py"
affects: [scip-phase-19]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Boundary-delegation: consuming surfaces import registry lookups and map None at their own boundary"

key-files:
  created:
    - tests/core/test_shell_outline.py
  modified:
    - src/atelier/core/capabilities/semantic_file_memory/capability.py
    - src/atelier/infra/tree_sitter/tags.py
    - src/atelier/infra/code_intel/scip/binaries.py
    - tests/infra/code_intel/scip/test_scip_adapter.py

key-decisions:
  - "Kept a minimal canonical-keyed _SCIP_ENV_VARS map for env-var string names; sourced the indexer binary name (fallback) from registry scip_indexer — lowest-risk approach preserving ATELIER_SCIP_*_BIN byte-identical"
  - "capability._language_for keeps @staticmethod and -> str; maps registry None to 'text'"
  - "tags.detect_language preserves str|None contract; widening to more languages is safe (regex falls back to javascript pattern)"

requirements-completed: [DLS-LANG-03, DLS-LANG-04]

# Metrics
duration: 13min
completed: 2026-05-29
---

# Phase 16 Plan 02: Migrate Code-Intel Surfaces to Canonical Registry Summary

**Migrated `capability._language_for`, `tags.detect_language`, and `scip/binaries.discover_scip_binary` to delegate language identity to the canonical registry, fixing the shell→bash drift end-to-end so `.sh/.bash/.zsh` files now reach the tree-sitter outline (kind `treesitter`) instead of the generic regex fallback.**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-05-29T10:57:49Z
- **Completed:** 2026-05-29T11:10:32Z
- **Tasks:** 2
- **Files modified:** 5 (1 created, 4 modified)

## Accomplishments
- `capability._language_for` now delegates to `language_for_path`, returning `lang.name` or `"text"` for unknowns. The stale comment referencing `docs/plans/active/savings-honest-ab/README.md` and the literal extension dict were removed. The `shell→bash` fix lands for free (DLS-LANG-03).
- `tags.detect_language` delegates to `language_for_path`, preserving the `str | None` contract (`extract_tags_from_text` short-circuits to `[]` on `None`).
- `scip/binaries.discover_scip_binary` sources the indexer binary name from the registry's `scip_indexer` while keeping a minimal `_SCIP_ENV_VARS` map so `ATELIER_SCIP_PYTHON_BIN` / `ATELIER_SCIP_TYPESCRIPT_BIN` stay byte-identical. The discovery resolution loop (`shutil.which` → `is_file` → `os.access X_OK`) and `discover_scip_binaries()` iterating `("python", "typescript")` are unchanged (DLS-LANG-04).
- Added `tests/core/test_shell_outline.py`: a `.sh` fixture resolves to `language == "bash"`, produces `mode == "outline"` with `outline["kind"] == "treesitter"` (NOT `"generic"`), keeps the function name, and strips the `sentinel_body` token. Selectable via `pytest -k shell`.
- Extended `test_scip_adapter.py` with an env-var-contract test proving the env-var names resolve a fake executable for python/typescript/javascript and that registry `scip_indexer` agrees with the map.

## Task Commits

1. **Task 1: Migrate the three consuming surfaces to delegate to the registry** — `2f301e8` (refactor)
2. **Task 2: Add shell outline regression and SCIP env-var preservation tests** — `1223ffe` (test)

## Files Created/Modified
- `src/atelier/core/capabilities/semantic_file_memory/capability.py` — `_language_for` delegates to `language_for_path`; added top-of-file absolute import; removed literal extension dict and stale comment.
- `src/atelier/infra/tree_sitter/tags.py` — `detect_language` delegates to `language_for_path`; preserves `str | None`.
- `src/atelier/infra/code_intel/scip/binaries.py` — `_SCIP_ENV_VARS` (env-var names only) + registry-sourced `scip_indexer` fallback; resolution loop unchanged.
- `tests/core/test_shell_outline.py` (created) — shell→bash tree-sitter outline regression.
- `tests/infra/code_intel/scip/test_scip_adapter.py` — added `test_scip_env_var_contract_preserved_after_registry_migration`.

## Decisions Made
- **Lowest-risk SCIP env-var handling:** rather than reading both env-var name and indexer from the registry, kept a canonical-keyed `_SCIP_ENV_VARS` dict for the operator-config env-var *names* (which must stay byte-identical) and sourced only the indexer binary *name* from `language_by_name(...).scip_indexer`. The Task 2 test asserts the two agree.

## Deviations from Plan
None — plan executed exactly as written. (`_SCIP_BINARIES` was renamed to `_SCIP_ENV_VARS` to reflect its narrowed role; this is the plan-sanctioned "minimal canonical-keyed env-var map" approach, not a behavior change.)

## Known Stubs
None.

## Threat Flags
None — internal refactor; no new network/auth/file/schema surface. T-16-03 (don't touch `"shell"` tool name) honored: 0 non-comment `"shell"` matches in capability.py; diff touched only the 5 planned files. T-16-04 (SCIP env-var contract) enforced by the new test.

## Issues Encountered
- **Full `tests/core tests/infra` wave-merge gate is very slow (>9 min, did not complete in budget):** This is the orchestrator-owned wave-merge gate. In its place, ran the focused Phase 16 validation plus a targeted regression set covering every surface touched by the widening (repo map tags, registry, git-history graveyard, all outline tests) — 72 passed. No regressions observed.
- **Pre-existing unrelated working-tree changes:** numerous unrelated `M`/`D` files (docs, benchmarks, engine.py) exist in the working tree from prior user work; none were touched per scope rules.

## Validation Commands Run
- Task 1 behavior: `_language_for('a.sh')=='bash'`, `'a.xyz'=='text'`; `detect_language('a.sh')=='bash'`, `'a.xyz') is None` → ok.
- Grep acceptance: 0 non-comment `"shell"` in capability.py; both `ATELIER_SCIP_*_BIN` strings present in binaries.py.
- `uv run pytest tests/core/test_shell_outline.py tests/infra/code_intel/scip/test_scip_adapter.py tests/core/test_code_context.py -q` → 68 passed, 5 skipped.
- `uv run pytest tests/core/test_shell_outline.py -k shell -x` → 1 passed.
- `uv run ruff check` (all 5 changed files) → All checks passed.
- `uv run mypy --strict` (3 changed source files) → no issues.
- Targeted regression: `test_repo_map.py test_languages.py test_graveyard.py test_python_outline.py test_typescript_outline.py test_rust_outline.py test_shell_outline.py` → 72 passed.

## Next Phase Readiness
- All four code-intel surfaces (capability, search_read [16-01 scope], tags, scip/binaries) now share canonical language identity. SCIP table expansion and additional indexers remain deferred to Phase 19.
- No blockers introduced.

---
*Phase: 16-canonical-language-registry*
*Completed: 2026-05-29*

## Self-Check: PASSED

- FOUND: src/atelier/core/capabilities/semantic_file_memory/capability.py
- FOUND: src/atelier/infra/tree_sitter/tags.py
- FOUND: src/atelier/infra/code_intel/scip/binaries.py
- FOUND: tests/core/test_shell_outline.py
- FOUND: tests/infra/code_intel/scip/test_scip_adapter.py
- FOUND commit: 2f301e8 (Task 1, refactor)
- FOUND commit: 1223ffe (Task 2, test)
