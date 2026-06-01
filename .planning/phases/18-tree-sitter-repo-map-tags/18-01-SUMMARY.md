# Phase 18 Plan 01 Summary — Shared tree-sitter tag extraction

## Completed

- Exposed public tree-sitter parser/config helpers from `treesitter_ast.py`.
- Added tree-sitter tag extraction for configured languages in `tags.py`.
- Preserved Python AST extraction and legacy regex fallback for JavaScript, TypeScript, Go, and Rust parser failures.
- Returned `[]` instead of regex garbage for parser-missing non-legacy tree-sitter languages.
- Added focused extraction tests for Java, Ruby, C, C++, C#, Kotlin, PHP, Swift, Scala, bash, SQL, TOML, YAML, and JSON.
- Added data-language safeguards for definition-only tags, bounded JSON keys, parser-missing behavior, malformed input, and byte-range correctness.

## Validation

- `uv run pytest tests/infra/tree_sitter/test_tags.py tests/core/test_repo_map.py tests/infra/code_intel/git_history/test_graveyard.py -q`
- `uv run ruff check src/atelier/infra/tree_sitter/tags.py src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py tests/infra/tree_sitter/test_tags.py tests/core/test_repo_map.py`
- `uv run mypy --strict src/atelier/infra/tree_sitter/tags.py src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py`
