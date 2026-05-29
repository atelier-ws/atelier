---
phase: 17-tree-sitter-outline-coverage
plan: 01
subsystem: code-intel
tags: [tree-sitter, outline, smart_read, bash, toml, semantic-file-memory]

# Dependency graph
requires:
  - phase: 16-language-registry
    provides: canonical language registry (bash/toml keys via language_by_name)
provides:
  - "Generalized outline_text engine with recursive visit() (unwrap + keep_first_line)"
  - "LangCfg.unwrap and LangCfg.keep_first_line frozenset fields"
  - "Tuned bash outline config (export/declare surfaced, command noise dropped)"
  - "New toml outline config (table headers + top-level pairs)"
affects: [17-02-sql-yaml-json-outline, code-intel, smart_read]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Recursive visit() AST walk descending only transparent unwrap kinds"
    - "keep_first_line first-line emit for data-key/value grammars"
    - "Backward-compatible LangCfg field addition (append + empty-frozenset default)"

key-files:
  created:
    - tests/core/test_toml_outline.py
  modified:
    - src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py
    - tests/core/test_shell_outline.py

key-decisions:
  - "Append unwrap/keep_first_line at END of LangCfg, defaulted empty, so all 12 existing frozen configs collapse to old flat-loop behavior"
  - "Engine adds NO savings guard; capability.smart_read 25% guard stays the single authority"
  - "toml top-level pairs are direct root children (keep_full); table/array headers emit first line only (keep_first_line); nested pairs terminate and are dropped"

patterns-established:
  - "unwrap descent: only unwrap kinds recurse; kept nodes terminate to preserve top-level-only output"
  - "keep_first_line: decode node bytes, emit first splitline rstripped (or b'' if empty)"

requirements-completed: [DLS-OUTLINE-01, DLS-OUTLINE-04]

# Metrics
duration: ~20min
completed: 2026-05-29
---

# Phase 17 Plan 01: Tree-sitter Outline Engine Generalization Summary

**Refactored `outline_text` from a flat root-children loop into a recursive `visit()` that transparently descends `unwrap` wrapper nodes and emits first-lines for `keep_first_line` data keys — preserving byte-for-byte backward compatibility for the 12 existing languages, then validated the engine by tuning `bash` and adding `toml`.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3 completed
- **Files modified:** 2 (1 created, 2 modified)

## Accomplishments
- Generalized the outline engine: `LangCfg` gained `unwrap` + `keep_first_line` fields (appended, defaulted empty) and `outline_text` now uses a recursive `visit()` walk that descends only transparent wrapper kinds — the structural foundation Plan 17-02's SQL/YAML/JSON grammars require.
- Tuned the `bash` config so `export`/`declare` lines surface (`declaration_command`) while bare top-level command/comment noise is dropped; functions kept as signatures, bodies stripped.
- Added the `toml` config (top-level pairs verbatim + `[table]`/`[[array]]` headers as first lines, nested table values dropped) and a full-pipeline test proving `.toml` reaches the treesitter outline kind.
- All 8 pre-existing outline tests stay green (rust/shell/python/typescript), confirming the empty-default invariant reproduces the old flat-loop output exactly.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing TOML outline test** - `2d95834` (test)
2. **Task 2: Extend LangCfg + refactor outline_text into recursive visit()** - `6b9e7ee` (refactor)
3. **Task 3: Tune bash config, add toml config, update shell test** - `b935916` (feat)

_Task 1 deliberately establishes RED (no toml config), Task 2 preserves green for existing langs, Task 3 turns toml green._

## Files Created/Modified
- `tests/core/test_toml_outline.py` (created) - Full-pipeline `smart_read` test asserting `.toml` resolves to `language == "toml"`, `mode == "outline"`, `outline["kind"] == "treesitter"`; table headers + top-level pair keys present, nested table values absent.
- `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` (modified) - Appended `unwrap`/`keep_first_line` LangCfg fields; replaced flat root loop with recursive `visit()`; tuned `bash` entry; added `toml` entry.
- `tests/core/test_shell_outline.py` (modified) - Retuned bash assertions: larger fixture, asserts `export`/`declare` lines surfaced and bare top-level command invocations dropped.

## Deviations from Plan

None - plan executed exactly as written. The pre-commit hook auto-formatted `tests/core/test_shell_outline.py` once (cosmetic); re-staged and committed without code changes.

## Threat Model Coverage
- **T-17-01 (DoS via recursion):** Mitigated — `visit()` recurses only into finite `unwrap` kinds and never into kept nodes; `parser.parse` remains wrapped in try/except returning `None` on failure.
- **T-17-02 (regression for 12 existing langs):** Mitigated — empty `unwrap`/`keep_first_line` make `visit(root)` identical to the old flat loop; `tests/core -k outline` (9 tests) green.
- **T-17-SC (package installs):** Accepted — no installs; grammars ship in vetted `tree-sitter-language-pack`.

## Known Stubs
None.

## Validation Run
- `uv run pytest tests/core/test_shell_outline.py tests/core/test_toml_outline.py tests/core/test_rust_outline.py -q` → 3 passed
- `uv run pytest tests/core -k outline -q` → 9 passed, 784 deselected
- `uv run ruff check src/.../treesitter_ast.py tests/core/test_shell_outline.py tests/core/test_toml_outline.py` → All checks passed
- `uv run mypy --strict src/.../treesitter_ast.py` → Success: no issues found

## Self-Check: PASSED
- `tests/core/test_toml_outline.py` — FOUND
- `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` — FOUND (modified)
- `tests/core/test_shell_outline.py` — FOUND (modified)
- Commits `2d95834`, `6b9e7ee`, `b935916` — FOUND in git log
