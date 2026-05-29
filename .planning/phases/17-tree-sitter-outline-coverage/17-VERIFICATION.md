---
phase: 17-tree-sitter-outline-coverage
verified: 2026-05-29T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  note: initial verification
---

# Phase 17: Tree-sitter Outline Coverage Verification Report

**Phase Goal:** Shell, YAML, TOML, JSON, and SQL get dedicated tree-sitter structural outlines where grammar/savings allow.
**Verified:** 2026-05-29
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | Shell scripts produce tree-sitter outlines with meaningful function and assignment structure instead of generic regex outlines | ✓ VERIFIED | `bash` `_LANG_CONFIG` keeps `variable_assignment`+`declaration_command` (keep_full), `function_definition` (keep_signature), strips `compound_statement` bodies (treesitter_ast.py:297-300). `test_shell_outline.py` asserts `kind=="treesitter"`, functions `run_build`/`deploy` + `export DEPLOY_ENV` + `declare -r MAX_RETRIES` kept, `sentinel_body`/`ls -la` body noise dropped — PASS |
| 2 | SQL files produce outlines showing schema-level constructs (tables, views, functions, indexes) | ✓ VERIFIED | `sql` config unwraps `statement`, keep_signature `create_table/view/index/function/alter_table`, strips bodies (treesitter_ast.py:306-310). `test_sql_outline.py` asserts all four construct names present + `sentinel_body_token` absent. Live spot-check confirmed table/view/index names emitted — PASS |
| 3 | YAML, TOML, and JSON expose top-level document structure rather than noisy scalar-heavy outlines | ✓ VERIFIED | `yaml` unwrap `stream/document/block_node/block_mapping` + keep_first_line `block_mapping_pair`; `toml` keep_full `pair` + keep_first_line `table/table_array_element`; `json` unwrap `document/object` + keep_first_line `pair` (treesitter_ast.py:301-320). Tests assert top-level keys present, deeply-nested scalars/secrets absent — PASS |
| 4 | Dedicated outlines only ship when parser availability and the existing 25% savings guard make them better than generic | ✓ VERIFIED | `capability.smart_read` guard `len(ts_text) <= int(len(source)*0.75)` untouched and authoritative (capability.py:340). Engine adds NO internal guard. `test_json_small_flat_degrades_via_guard` proves compact JSON (~96% ratio) is rejected → generic/full — PASS |
| 5 | Missing grammars or low-value outlines degrade cleanly to the generic path | ✓ VERIFIED | `outline_text` returns `None` for unknown language, missing parser, or parse exception (treesitter_ast.py:410-420). Live spot-check: `outline_text('not_a_lang', ...)` → `None`. Small/flat JSON degrades via guard — PASS |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` | LangCfg.unwrap + keep_first_line, recursive visit() engine, bash/toml/sql/yaml/json configs | ✓ VERIFIED | 451 lines. `unwrap`/`keep_first_line` fields appended at end of LangCfg (lines 52-54). Recursive `visit()` (lines 425-448) descends only `unwrap` kinds, terminates on kept nodes (line 446). 12 pre-existing configs unchanged. 5 new/tuned entries present |
| `tests/core/test_shell_outline.py` | Retuned bash assertions | ✓ VERIFIED | Asserts export/declare surfaced, command/comment noise dropped, bodies stripped |
| `tests/core/test_toml_outline.py` | TOML treesitter test | ✓ VERIFIED | `test_toml_outline_reaches_treesitter` — headers + pairs present, nested values absent |
| `tests/core/test_sql_outline.py` | SQL schema-construct test | ✓ VERIFIED | `test_sql_outline_reaches_treesitter` — 4 constructs present, body absent |
| `tests/core/test_yaml_outline.py` | YAML top-level key test | ✓ VERIFIED | `test_yaml_outline_reaches_treesitter` — top-level keys present, nested scalar absent |
| `tests/core/test_json_outline.py` | JSON two-case (large→treesitter, small→guard) | ✓ VERIFIED | `test_json_large_nested_reaches_treesitter` + `test_json_small_flat_degrades_via_guard` |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| treesitter_ast.outline_text | capability.smart_read 25% guard | `len(ts_text) <= int(len(source)*0.75)` | ✓ WIRED | capability.py:336-349 imports `outline_text as ts_outline_text`, calls it, gates result by guard. Untouched by phase |
| _LANG_CONFIG sql/yaml/json unwrap kinds | recursive visit() (17-01) | unwrap descent through wrapper nodes | ✓ WIRED | visit() recurses on `kind in cfg.unwrap` (line 428); configs supply wrapper kinds |
| _LANG_CONFIG keys (bash/toml/sql/yaml/json) | infra/code_intel/languages.py registry | canonical names, no new ext/parser map | ✓ WIRED | `tests/infra/code_intel/test_languages.py` 114 passed; languages resolve via registry |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| SUPPORTED_LANGUAGES includes new langs | `python -c "..."` | `['bash','json','sql','toml','yaml']` | ✓ PASS |
| Unknown language degrades cleanly | `outline_text('not_a_lang', 'x=1')` | `None` | ✓ PASS |
| SQL outline emits schema constructs | `outline_text('sql', ...)` | contains table/view/index names | ✓ PASS |
| Phase outline test suite | `pytest test_{shell,sql,yaml,toml,json,rust}_outline.py -q` | 7 passed | ✓ PASS |
| Outline regression set | `pytest tests/core -k outline -q` | 13 passed, 784 deselected | ✓ PASS |
| Registry + code_context | `pytest tests/infra/code_intel/test_languages.py tests/core/test_code_context.py -q` | 114 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| DLS-OUTLINE-01 | 17-01 | Shell/bash dedicated outlines with function + assignment structure | ✓ SATISFIED | bash config + test_shell_outline.py |
| DLS-OUTLINE-02 | 17-02 | SQL outlines for tables/views/functions/indexes | ✓ SATISFIED | sql config + test_sql_outline.py |
| DLS-OUTLINE-03 | 17-02 | YAML top-level document structure | ✓ SATISFIED | yaml config + test_yaml_outline.py |
| DLS-OUTLINE-04 | 17-01 | TOML table headers + top-level key/value | ✓ SATISFIED | toml config + test_toml_outline.py |
| DLS-OUTLINE-05 | 17-02 | JSON top-level structure when parser + 25% guard justify | ✓ SATISFIED | json config + two-case test (large→treesitter, small→guard degradation) |

No orphaned requirements: all five DLS-OUTLINE IDs map to a plan and a verified implementation.

### Anti-Patterns Found

None. No TBD/FIXME/XXX markers in phase-scope files. Both summaries report "Known Stubs: None". Engine adds no hardcoded empty returns beyond the documented clean-degradation `return None` paths. Tests contain substantive positive AND negative (sentinel-absence) assertions, not placeholders.

### Scope Discipline

All five phase commits (`2d95834`, `6b9e7ee`, `b935916`, `ddf43bc`, `9ae6c91`) touch only `treesitter_ast.py` and `tests/core/*_outline.py`. `git status` confirms no uncommitted changes to phase-scope files. The 25% guard authority in `capability.py` and the registry in `languages.py` were not modified.

### Human Verification Required

None. The phase goal is fully verifiable programmatically via the full-pipeline `smart_read` tests, which exercise the real outline path (parser → engine → guard) for each language. No visual, real-time, or external-service behavior involved.

### Note on Repository Gate

The full `make format-check`/`make test` repository gate reports failures OUTSIDE the Phase 17 change surface (unrelated dirty worktree: context_compression, mcp_server.py redundant-cast typecheck error, deleted/untracked benchmark and tests/core files). Per plan constraints these unrelated user WIP changes were not modified and are not Phase 17 blockers. `make lint` passed. All Phase 17 focused gates pass cleanly.

### Gaps Summary

No gaps. All five ROADMAP success criteria are observably true in the codebase, all five DLS-OUTLINE requirements satisfied, all artifacts substantive and wired, key links connected, the 25% savings guard intact and authoritative, and clean degradation confirmed for unknown grammars and low-value outlines. Phase goal achieved.

---

_Verified: 2026-05-29_
_Verifier: the agent (gsd-verifier)_
