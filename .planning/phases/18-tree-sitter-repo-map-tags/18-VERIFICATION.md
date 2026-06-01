# Phase 18 Verification — Tree-sitter Repo-map Tags

## Verdict

PASS — Phase 18 delivers tree-sitter-backed repo-map tags for configured tree-sitter languages while preserving Python AST extraction and legacy regex fallback boundaries.

## Evidence

- `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` now exposes public parser/config helpers for supported tree-sitter languages, definition node kinds, and transparent wrapper node kinds.
- `src/atelier/infra/tree_sitter/tags.py` routes configured tree-sitter languages through parser-backed extraction, keeps Python on stdlib `ast`, keeps JavaScript/TypeScript/Go/Rust regex fallback for parser failures, and returns `[]` for parser-missing non-legacy tree-sitter languages.
- `tests/infra/tree_sitter/test_tags.py` verifies extraction for Java, Ruby, C, C++, C#, Kotlin, PHP, Swift, Scala, bash, SQL, TOML, YAML, and JSON.
- Data-language fixtures verify definition-only tags, bounded JSON keys, parser-missing behavior, malformed-input safety, and byte-range correctness.
- `tests/core/test_repo_map.py` verifies repo-map graph ingestion for Java tags and guards against YAML common-key reference edges.

## Validation

- `uv run ruff check src/atelier/infra/tree_sitter/tags.py src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py tests/infra/tree_sitter/test_tags.py tests/core/test_repo_map.py`
- `uv run mypy --strict src/atelier/infra/tree_sitter/tags.py src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py`
- `uv run pytest tests/infra/tree_sitter/test_tags.py tests/core/test_repo_map.py tests/infra/code_intel/git_history/test_graveyard.py -q`

## Requirement coverage

- DLS-TAGS-01 — Complete
- DLS-TAGS-02 — Complete
- DLS-TAGS-03 — Complete
- DLS-TAGS-04 — Complete
