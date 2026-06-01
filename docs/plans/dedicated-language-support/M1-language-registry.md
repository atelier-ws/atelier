# M1 — Canonical Language Registry

**Goal:** Make one module the single source of truth for language identity, and
have every code-intel surface read from it. Fix the shell/bash mismatch as the
first concrete payoff.

## Why first

Four surfaces (extension detection, tree-sitter outline, repo-map tags, SCIP
registry) each hard-code their own language spellings. The shell/bash bug
(`.sh` → `"shell"` but the tree-sitter key is `"bash"`) is one symptom. Without
a shared registry, M2–M5 would re-introduce the same class of drift.

## Files to touch

- **New:** `src/atelier/infra/code_intel/languages.py` — canonical registry.
- `src/atelier/core/capabilities/semantic_file_memory/capability.py`
  (`_detect_language`) — delegate to the registry.
- `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py`
  (`_LANG_CONFIG` keys, `SUPPORTED_LANGUAGES`) — key on canonical names.
- `src/atelier/infra/tree_sitter/tags.py` (`detect_language`) — delegate.
- `src/atelier/infra/code_intel/scip/binaries.py` (`_SCIP_BINARIES`) — key on
  canonical names.

## Approach

1. Define a `Language` dataclass and a `LANGUAGES` table in the new module:

   ```python
   @dataclass(frozen=True)
   class Language:
       name: str                 # canonical key, == tree-sitter-pack parser name
       extensions: frozenset[str]
       parser_name: str          # tree-sitter-language-pack key
       scip_indexer: str | None  # e.g. "scip-go"; None if no indexer
   ```

   Canonical `name` == tree-sitter-language-pack parser name (`bash`, not
   `shell`; `c_sharp` or `csharp` — match whatever the pack uses). Provide:
   - `language_for_path(path) -> Language | None`
   - `language_by_name(name) -> Language | None`
   - module-level constants `EXTENSION_TO_LANGUAGE`, `ALL_LANGUAGES`.
2. Migrate `_detect_language` to call `language_for_path(...).name` with the
   `"text"` fallback preserved. **Resolve `shell` → `bash`** here so the
   existing tree-sitter bash config is finally reachable.
3. Re-key `_LANG_CONFIG` (or add a thin alias map) so its keys equal canonical
   names. `SUPPORTED_LANGUAGES` stays derived from `_LANG_CONFIG.keys()`.
4. Replace the ad-hoc dicts in `tags.py::detect_language` and
   `scip/binaries.py::_SCIP_BINARIES` with lookups against the registry.
5. Keep public function signatures stable (they return language *strings*); only
   the source of those strings changes.

## Verify

- New unit test: every extension in the old `_detect_language` map resolves to
  the same (or canonicalized) language via the registry, and `.sh` now resolves
  to a name present in `SUPPORTED_LANGUAGES`.
- Regression: an existing shell fixture now produces a `kind: "treesitter"`
  outline (not `kind: "generic"`).
- `make lint && make typecheck && uv run pytest tests/core/test_code_context.py tests/infra -q`.
