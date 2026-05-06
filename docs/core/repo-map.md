# Repo Map

`atelier_repo_map` builds a token-budgeted map of important repository symbols and imports.

## What It Does

The builder extracts deterministic tags from Python, JavaScript, TypeScript, Go, and Rust files, builds a dependency graph, ranks nodes with PageRank, and renders the highest-value symbols within the requested token budget.

## MCP Shape

```json
&#123;
  "path": ".",
  "focus": "memory arbitration",
  "budget_tokens": 1200
&#125;
```

The response contains the rendered map, the file count, node count, and token estimate. It is intended for broad navigation before deeper reads.

## Limits

The current extractor is deterministic and stdlib-first. Query files are present for future tree-sitter integration, but V3.1-B does not require native parser packages at runtime.
