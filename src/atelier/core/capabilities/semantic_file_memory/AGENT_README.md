# semantic_file_memory

## Purpose

Maintains a content-addressed semantic cache for source files, symbol retrieval, and change-impact analysis.

## Entry Point

`__init__.py` re-exports `SemanticFileMemoryCapability`.

## Module Layout

| File                | Responsibility                                                             |
| ------------------- | -------------------------------------------------------------------------- |
| `capability.py`     | Orchestrator: summarization, cache reads, search hooks, git-aware metadata |
| `indexer.py`        | SHA-256 content-addressed JSON index                                       |
| `search.py`         | BM25 + dependency-graph search and impact analysis                         |
| `python_ast.py`     | Python AST extraction                                                      |
| `typescript_ast.py` | Tree-sitter-first TS/JS analysis with regex fallback                       |
| `models.py`         | `SemanticSummary`, `SymbolInfo`, `ImportInfo`, `ChangeImpact`              |

## Key Contracts

- `summarize_file(path, max_lines=120)` -> `SemanticSummary`
- `semantic_search(query, limit=10)` -> `list[dict[str, Any]]`
- `_load()` returns raw index dict with `files` key
- Summary payload now includes git metadata fields when available:
  - `git_last_commit`
  - `git_last_author_date`

## Notes

- Git metadata uses `GitPython` when installed (empty values otherwise)
- Tree-sitter parser path is optional; regex analyzer remains the stable fallback

## Where to look next

- `src/atelier/core/runtime/engine.py`
