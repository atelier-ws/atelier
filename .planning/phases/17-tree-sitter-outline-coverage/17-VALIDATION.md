# Phase 17: Tree-sitter Outline Coverage - Validation Strategy

**Created:** 2026-05-29
**Nyquist target:** every observable behavior promised by DLS-OUTLINE-01 through DLS-OUTLINE-05 has a direct test, plus regression coverage for existing outline languages.

## Acceptance Criteria

| Requirement | Acceptance signal | Test command |
|-------------|-------------------|--------------|
| DLS-OUTLINE-01 | `.sh` files return `outline.kind == "treesitter"` with assignments/exports/functions kept and command bodies stripped | `uv run pytest tests/core/test_shell_outline.py -q` |
| DLS-OUTLINE-02 | `.sql` files return tree-sitter schema outlines for table, view, index, and function constructs with bodies stripped | `uv run pytest tests/core/test_sql_outline.py -q` |
| DLS-OUTLINE-03 | `.yaml` files return top-level document keys only, excluding nested scalar noise | `uv run pytest tests/core/test_yaml_outline.py -q` |
| DLS-OUTLINE-04 | `.toml` files return table headers and top-level key/value structure | `uv run pytest tests/core/test_toml_outline.py -q` |
| DLS-OUTLINE-05 | large/nested `.json` can return tree-sitter top-level structure, while small/flat JSON degrades via the existing 25% guard | `uv run pytest tests/core/test_json_outline.py -q` |

## Regression Matrix

| Surface | Why it matters | Command |
|---------|----------------|---------|
| Existing outline languages | `outline_text` will be refactored; existing Rust/Python/TypeScript/shell behavior must not regress | `uv run pytest tests/core -k outline -q` |
| Registry handoff | New `_LANG_CONFIG` keys must align with Phase 16 canonical names | `uv run pytest tests/infra/code_intel/test_languages.py tests/core/test_code_context.py -q` |
| Focused changed files | Lint/type safety for changed source and tests | `uv run ruff check src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py tests/core/test_shell_outline.py tests/core/test_sql_outline.py tests/core/test_yaml_outline.py tests/core/test_toml_outline.py tests/core/test_json_outline.py` and `uv run mypy --strict src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` |

## Wave Gates

1. **Wave 1 / Plan 17-01:** engine refactor, bash tuning, TOML outline.
   - Required checks: `uv run pytest tests/core/test_shell_outline.py tests/core/test_toml_outline.py tests/core/test_rust_outline.py -q`
   - Guard check: `uv run pytest tests/core -k outline -q`

2. **Wave 2 / Plan 17-02:** SQL, YAML, JSON outline coverage.
   - Required checks: `uv run pytest tests/core/test_sql_outline.py tests/core/test_yaml_outline.py tests/core/test_json_outline.py -q`
   - Guard check: `uv run pytest tests/core -k outline -q`

## Phase Gate

Run after both plans complete:

```bash
uv run pytest tests/core/test_shell_outline.py tests/core/test_sql_outline.py tests/core/test_yaml_outline.py tests/core/test_toml_outline.py tests/core/test_json_outline.py tests/core/test_rust_outline.py -q
uv run pytest tests/core -k outline -q
uv run pytest tests/infra/code_intel/test_languages.py tests/core/test_code_context.py -q
make lint && make typecheck && make test
```

If the full repository gate reports failures outside the Phase 17 change surface, document them precisely and do not modify unrelated user changes just to make the gate pass.
