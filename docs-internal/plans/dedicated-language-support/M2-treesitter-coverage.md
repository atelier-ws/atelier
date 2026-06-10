# M2 — Tree-sitter Outline Coverage for Remaining Languages

**Goal:** Replace the generic regex outline with dedicated tree-sitter
`LangCfg` entries for the languages that currently only get generic treatment:
**shell** (after M1 fix), **yaml**, **toml**, **json**, **sql**.

## Files to touch

- `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py`
  (`_LANG_CONFIG`).
- `tests/core/` — new per-language fixtures.

## Approach

For each language, add a `LangCfg` keyed on the canonical name (M1). The
existing `outline_text` machinery (`keep_full` / `keep_signature` / `container`
/ `member` / `body_kinds`) handles the rest — no engine changes needed if the
language is in `SUPPORTED_LANGUAGES` and the parser loads.

Proposed node-kind allowlists (verify exact kinds against the actual grammar
with the snippet in the Verify step — grammar node names vary):

- **shell/bash** — already configured as `bash`; M1 makes it reachable. Confirm
  `function_definition`, `variable_assignment` outline real scripts well; tune
  `keep_full` (drop noisy `command`/`comment` if they bloat output past the
  25% guard).
- **sql** — keep `create_table`, `create_view`, `create_function`,
  `create_index` statements as signatures; this gives a schema-at-a-glance.
- **yaml** — keep top-level `block_mapping_pair` keys only (document structure),
  not nested scalars. Data-language outline = top-level keys.
- **toml** — keep `table` / `table_array_element` headers and top-level
  key/value pairs.
- **json** — keep top-level object keys only. (Low value; gate behind the 25%
  savings guard — if it never clears, it simply stays on the generic path,
  which is acceptable.)

The 25% savings guard in `capability.py` already protects against shipping a
"dedicated" outline that is no better than generic — so adding a config is safe
even where the win is marginal.

## Verify

- Parser availability probe (run once per language during dev):

  ```python
  from tree_sitter_language_pack import get_parser
  get_parser("yaml"); get_parser("toml"); get_parser("json"); get_parser("sql")
  ```

  If a grammar is missing from the pack, record it in the index.md open
  questions and leave that language on the generic path.
- Fixture test per language: a representative file produces
  `outline.kind == "treesitter"` and the outline contains the expected
  top-level symbols/keys.
- `uv run pytest tests/core -k outline -q && make lint && make typecheck`.
