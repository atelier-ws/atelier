# M3 — Tree-sitter Repo-map Symbol Tags

**Goal:** The PageRank repo map only gets symbols for Python (AST) and
JS/TS/Go/Rust (regex). Give every tree-sitter language real definition tags by
reusing the grammars from `treesitter_ast.py`, replacing the brittle regex
tagger.

## Files to touch

- `src/atelier/infra/tree_sitter/tags.py`
  (`_regex_tags`, `extract_tags_from_text`, `detect_language`).
- `src/atelier/core/capabilities/repo_map/graph.py` (consumer — verify no
  changes needed; it should just receive more tags).
- `tests/infra/` — new per-language tag fixtures.

## Approach

1. Add a `_treesitter_tags(path, text, language)` function that walks the parse
   tree and emits a `Tag(kind="definition")` for each node in the language's
   `container` ∪ `member` ∪ `keep_signature` sets (reuse `_LANG_CONFIG`), and
   `kind="reference"` for identifier nodes. Extract the name via the grammar's
   `name`/`identifier` child (helper per language, or a small name-field map).
2. Routing in `extract_tags_from_text`:
   - Python → keep the existing `ast`-based `_python_tags` (richest).
   - Any language in `SUPPORTED_LANGUAGES` (tree-sitter) → `_treesitter_tags`.
   - Everything else → existing `_regex_tags` fallback (keep it for unknowns).
3. `detect_language` delegates to the M1 registry (drop the local dict).
4. Keep the `Tag` dataclass and `byte_range` semantics identical so the repo
   map / PageRank consumer is unaffected.

## Why reuse `_LANG_CONFIG`

The outline configs already encode "what is a definition" per language. Reusing
them keeps tags and outlines consistent and avoids a second per-language
maintenance surface. Consider exposing a shared helper from `treesitter_ast.py`
(e.g. `definition_node_kinds(language)`) rather than importing the private dict.

## Verify

- Fixture test: a Go/Java/Ruby/etc. file yields definition tags for its
  top-level functions/classes (regex tagger produced none for Java/Ruby/etc.).
- Repo-map smoke test: PageRank over a fixture repo now ranks symbols from a
  previously-unsupported language.
- `uv run pytest tests/infra -k tags -q && make lint && make typecheck`.
