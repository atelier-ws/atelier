# Phase 17: Tree-sitter Outline Coverage - Research

**Researched:** 2026-05-29
**Domain:** tree-sitter structural outline extraction for data/config/script languages (bash, sql, yaml, toml, json)
**Confidence:** HIGH (all parser availability and node kinds verified live via `uv run` against the installed `tree-sitter-language-pack` 1.8.1)

## Summary

Phase 17 adds dedicated tree-sitter outlines for **bash, sql, yaml, toml, json** to the existing
data-driven outliner in `treesitter_ast.py`. Phase 16 already canonicalized the language keys (bash,
sql, yaml, toml, json all exist in `languages.py`) and wired the `_LANG_CONFIG` → `SUPPORTED_LANGUAGES`
→ `capability.smart_read` path with a 25% savings guard. **No new dependency is needed** — every
required grammar ships in the already-installed `tree-sitter-language-pack` 1.8.1 and was verified to
parse live in this session.

The single most important finding: **the current `outline_text` engine only inspects the *direct
children of the root node*.** That works for bash and toml (their declarations sit at the top level)
but **fails for sql, yaml, and json**, whose meaningful structure is buried inside transparent wrapper
nodes (`statement` for SQL, `stream→document→block_node→block_mapping` for YAML, `document→object` for
JSON). Today `outline_text("sql"|"yaml"|"json", ...)` returns `None` (verified). The phase therefore
requires a **small, backward-compatible engine enhancement** — a recursive "descend through wrapper
kinds" mechanism plus a "keep first line" emit mode for data-language key/value nodes — in addition to
the five `LangCfg` entries.

**Primary recommendation:** Extend `LangCfg` with two new frozenset fields (`unwrap`, `keep_first_line`)
and refactor `outline_text` from a flat root-children loop into a recursive `visit()` that transparently
descends `unwrap` kinds and never recurses into kept nodes (preserving top-level-only semantics and
exact backward compatibility for the 12 existing languages). Add tuned configs for bash/sql/toml and
the new descend-based configs for yaml/json. Keep the 25% guard authoritative — SQL and JSON will
legitimately fall back to the generic path on dense/small files, which is correct behavior (DLS-OUTLINE-05).

## User Constraints

No `CONTEXT.md` exists for this phase and no `copilot-instructions.md` exists in the repo. Constraints
are taken from ROADMAP success criteria, REQUIREMENTS, STATE watch points, and the M2 source design doc:

- **25% savings guard stays authoritative** — never ship a "dedicated" outline that isn't ≥25% smaller
  than the source; degrade to generic/full instead (ROADMAP SC4/SC5).
- **Missing grammars or low-value outlines must degrade cleanly** — no crashes (ROADMAP SC5).
- **Do NOT broaden into repo-map tags or SCIP** — those are Phases 18–20 (explicit scope guard).
- **Language registry drift forbidden** — do not add new extension/parser-key maps outside
  `languages.py` (STATE watch point). All `_LANG_CONFIG` keys must resolve via `language_by_name`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DLS-OUTLINE-01 | Shell/bash files produce dedicated outlines with function + assignment structure | bash already configured & reachable (Phase 16). Tuning verified: `keep_full={variable_assignment, declaration_command}`, `keep_signature={function_definition}` yields clean function+assignment outline at 50% of source (clears guard). |
| DLS-OUTLINE-02 | SQL files produce outlines for tables, views, functions, indexes | Verified `statement` wrapper → `create_table`/`create_view`/`create_index`/`create_function`/`alter_table`. Requires the `unwrap` engine enhancement. Signature-trimmed config clears guard at 67%. |
| DLS-OUTLINE-03 | YAML files produce top-level document-structure outlines | Verified 3-level wrapper (`stream→document→block_node→block_mapping`) → `block_mapping_pair`. Requires `unwrap` + `keep_first_line`. Top-level-keys outline = 18% of source (strong win). |
| DLS-OUTLINE-04 | TOML files produce table-header + top-level key/value outlines | Verified top-level `pair`/`table`/`table_array_element` are direct root children. Works with existing engine; `keep_first_line` for tables gives clean `[package]` headers at 43%. |
| DLS-OUTLINE-05 | JSON top-level object structure *when parser + 25% guard justify it* | Verified `document→object→pair`. Requires `unwrap`. Explicitly low-value: small/flat JSON stays on generic path (guard rejects at 90%); large nested config files win. Degradation is the designed behavior. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Node-kind allowlists per language | `treesitter_ast._LANG_CONFIG` (data) | — | Engine stays data-driven; adding a language is editing the table |
| Recursive structural extraction | `treesitter_ast.outline_text` (engine) | — | One engine serves all grammars; wrapper-descent logic lives here, not per-language |
| Savings gating / fallback ordering | `capability.smart_read` (orchestration) | — | 25% guard + fallback to generic/full already implemented; Phase 17 must not duplicate or weaken it |
| Language identity (ext→name, parser_name) | `infra/code_intel/languages.py` (registry) | — | Phase 16 canonical registry; Phase 17 consumes, never forks it |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `tree-sitter-language-pack` | 1.8.1 (installed) | Pre-built grammar bundle providing `get_parser("bash"\|"sql"\|"yaml"\|"toml"\|"json")` | Already a hard dependency (`pyproject.toml` line 45); all 5 grammars verified present this session |
| `tree-sitter` | ≥0.23 (installed) | Core parsing runtime | Already a dependency (`pyproject.toml` line 23) |

**No new packages required.** `## Package Legitimacy Audit` is therefore **not applicable** — Phase 17
installs nothing. All grammars are bundled in the already-vetted, already-installed `tree-sitter-language-pack`.

### Verified parser availability (live probe, 2026-05-29)
`uv run python -c "from tree_sitter_language_pack import get_parser; [get_parser(l) for l in ('bash','sql','yaml','toml','json')]"` → **all succeed**. [VERIFIED: live `uv run` probe against installed 1.8.1]

> **Binding gotcha (confirmed):** the language-pack `Node`/`Tree` objects expose attributes
> **as methods** (`tree.root_node`, `node.child_count`, `node.start_byte` are callables), and
> `parser.parse()` requires a **`str`**, not `bytes`. The existing `_node_attr` helper already
> handles the method-vs-value duality, and `outline_text` already passes `source` (str). Any new
> probe/code must use `_node_attr` (or call the methods), **not** bare `getattr(node, "type")`.

## Architecture Patterns

### System Architecture Diagram (outline resolution flow in `smart_read`)

```
file ──► _language_for(path) ──► language (registry, Phase 16)
                                    │
        effective_loc > threshold ? │  (else: full)
                                    ▼
   ┌─ python/typescript/javascript ─► dedicated AST outline (unchanged) ─► return
   │
   ├─ language ∈ SUPPORTED_LANGUAGES ─► treesitter_ast.outline_text(language, source)
   │                                        │
   │                                        ├─ None (no cfg / parser fail / no pieces)
   │                                        │      └─► fall through
   │                                        └─ text, AND len(text) ≤ 0.75·len(source) ?
   │                                               YES ─► kind="treesitter" ─► return
   │                                               NO  ─► fall through (guard rejects)
   │
   ├─ language != "text" ─► _generic_outline_text (regex) ─► same 0.75 guard ─► kind="generic"
   │
   └─ full file ─► mode="full"
```

The Phase 17 change is **entirely inside the `outline_text(...)` box** plus the `_LANG_CONFIG` table.
`smart_read`'s ordering and guard are already correct and must be left untouched.

### Pattern 1: Transparent wrapper descent (NEW — required for sql/yaml/json)
**What:** Some grammars wrap declarations in semantically-empty container nodes that the current flat
root-children loop never sees through.
**When to use:** Any language whose meaningful declarations are not direct children of the root.
**Verified wrapper chains** [VERIFIED: live `uv run` tree dump]:
- **SQL:** `program → statement → create_table | create_view | create_index | create_function | alter_table`
- **YAML:** `stream → document → block_node → block_mapping → block_mapping_pair`
- **JSON:** `document → object → pair`

**Recommended engine shape** (prototype verified this session to produce correct outlines):
```python
# Source: prototyped & verified via uv run, 2026-05-29
def visit(node):
    for child in _children(node):
        k = _kind(child)
        if k in cfg.unwrap:                 # transparent descend (recursive)
            visit(child)
        elif k in cfg.keep_full:
            pieces.append(full_range(child))
        elif k in cfg.keep_signature:
            pieces.append(_signature_slice(source_bytes, child, cfg.body_kinds))
        elif k in cfg.keep_first_line:      # NEW emit mode for data languages
            pieces.append(first_line_of(child))
        elif k in cfg.container:
            pieces.append(_signature_slice(...)); pieces.extend(_extract_member_signatures(...))
        # else: skip — and crucially do NOT recurse (keeps output top-level only)
visit(root)
```
**Backward-compat note:** the 12 existing languages all have empty `unwrap`/`keep_first_line`, so
`visit(root)` collapses to exactly the current flat loop over root children — zero behavior change.
Verified: `make`-style `uv run pytest tests/core -k outline` (8 tests incl. rust/shell) currently passes
and the refactor must keep all 8 green.

### Pattern 2: First-line emit for data key/value nodes (NEW)
**What:** For YAML/JSON/TOML, emit only the first source line of each kept top-level key node.
**Why:** Data grammars use *symmetric* node kinds (a YAML key and a scalar value are both `flow_node`),
so the body-trimming `_signature_slice` cannot distinguish key from value. First-line emission is the
clean primitive: `name: ci` stays, `on:` (with nested mapping) collapses to just `on:`.
**Verified output (YAML):** top-level keys `name: ci / on: / jobs: / version: 1`, **18% of source**.

### Recommended `_LANG_CONFIG` entries (verified to produce correct outlines this session)
```python
# bash — TUNE existing entry: drop noisy `command`/`comment`, add `declaration_command` (export/declare)
"bash": LangCfg(
    keep_full=frozenset({"variable_assignment", "declaration_command"}),
    keep_signature=frozenset({"function_definition"}),
    body_kinds=frozenset({"compound_statement"}),
),  # verified: 50% of source, functions+assignments kept, bodies stripped

# sql — NEW: unwrap the `statement` wrapper; signature-trim table/function bodies
"sql": LangCfg(
    unwrap=frozenset({"statement"}),
    keep_signature=frozenset({"create_table", "create_view", "create_index",
                              "create_function", "alter_table"}),
    body_kinds=frozenset({"column_definitions", "function_body", "create_query", "index_fields"}),
),  # verified: 67% of source; shows all 4 schema construct types

# yaml — NEW: descend 3 wrapper levels, keep top-level mapping keys' first line only
"yaml": LangCfg(
    unwrap=frozenset({"stream", "document", "block_node", "block_mapping"}),
    keep_first_line=frozenset({"block_mapping_pair"}),
),  # verified: 18% of source

# toml — NEW: top-level pairs verbatim, table headers as first line
"toml": LangCfg(
    keep_full=frozenset({"pair"}),
    keep_first_line=frozenset({"table", "table_array_element"}),
),  # verified: 43% of source; clean `[package]` / `[[bin]]` headers

# json — NEW: descend document→object, keep top-level pair first line (low value, guard-gated)
"json": LangCfg(
    unwrap=frozenset({"document", "object"}),
    keep_first_line=frozenset({"pair"}),
),  # verified: parses; small/flat JSON correctly rejected by 25% guard → generic path
```

### Anti-Patterns to Avoid
- **Putting `statement`/`object` in `keep_full`** to "make SQL/JSON work": keeps entire bodies, blows
  the 25% guard, and emits unusable noise. Use `unwrap` instead.
- **Recursing into kept nodes:** would explode YAML/JSON to every nested key. Only `unwrap` kinds recurse.
- **Weakening or relocating the 25% guard:** the guard in `capability.smart_read` is the single
  authority that prevents fake savings. Phase 17 must not duplicate it inside `outline_text`.
- **Adding extension/parser maps anywhere but `languages.py`:** registry drift (STATE watch point).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parsing bash/sql/yaml/toml/json | A regex/line-based structural extractor | `tree-sitter-language-pack` grammars (already installed) | Grammars handle multiline values, heredocs, nested mappings, dollar-quoted SQL bodies — the existing `_generic_outline_text` regex is precisely the fallback we're trying to beat |
| Savings/fallback decision | A new guard in `outline_text` | Existing `len(text) ≤ 0.75·len(source)` guard in `smart_read` | Already implemented, already tested, single source of truth |
| Language identity | Inline ext→lang dict | `languages.py` registry (Phase 16) | Registry drift is an explicit watch point |

**Key insight:** Phase 16 already built the entire pipeline and guard. Phase 17 is *mostly data* (5
config entries) plus *one focused engine generalization* (wrapper descent). Resist any temptation to
re-architect `smart_read`.

## Common Pitfalls

### Pitfall 1: Fixtures too small to clear the 25% guard
**What goes wrong:** A tiny fixture's outline isn't ≤75% of source, so `smart_read` falls through to
generic/full and the test asserting `kind=="treesitter"` fails.
**Why it happens:** SQL (67%) and JSON (90% on small files) are *dense* — the guard margin is thin.
**How to avoid:** Use realistic fixtures with substantial trimmable content: SQL with a multi-line
`CREATE FUNCTION` body and wide tables; JSON with deeply nested objects/arrays. Verified: a 4-statement
SQL file clears at 67%; a flat 5-key JSON file does NOT clear (90%) and is *expected* to stay generic.
**Warning signs:** test sees `outline["kind"] == "generic"` instead of `"treesitter"`.

### Pitfall 2: Refactor regresses the 12 existing languages
**What goes wrong:** Rewriting `outline_text` into a recursive walk subtly changes go/rust/java output.
**How to avoid:** Empty `unwrap`/`keep_first_line` must make `visit(root)` identical to the current
flat loop. Run `uv run pytest tests/core -k outline` (rust + shell, 8 tests) before and after — must
stay green. Add no recursion for non-`unwrap` kinds.
**Warning signs:** `test_rust_outline_keeps_container_bodies_out` starts emitting member bodies.

### Pitfall 3: Treating the binding's method attributes as values
**What goes wrong:** `node.type` / `tree.root_node` raise `AttributeError` or return a bound method,
because the language-pack binding exposes them as **callables**.
**How to avoid:** Always go through `_node_attr` (handles `val() if callable(val)`). Never `getattr(node, "type")` directly.
**Warning signs:** `'builtins.Node' object has no attribute 'type'` or `'builtin_function_or_method' object has no attribute ...`.

### Pitfall 4: JSON/SQL "doesn't work" — actually the guard rejecting correctly
**What goes wrong:** Engineer sees small JSON return generic and assumes a bug.
**How to avoid:** This is DLS-OUTLINE-05 by design. Document in tests with a comment; assert the
*degradation* path for small JSON and the *treesitter* path for a large nested fixture.

## Runtime State Inventory

> Not applicable — Phase 17 is a pure code + config + test change. No stored data, live-service config,
> OS-registered state, secrets/env vars, or build artifacts embed any renamed string.
> **None — verified:** the change is additive (`_LANG_CONFIG` entries + `outline_text` generalization);
> no migration of stored data and no rename of any persisted key.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest`) |
| Config file | `pyproject.toml` (pytest settings); per-test files under `tests/core/` |
| Quick run command | `uv run pytest tests/core -k outline -q` (currently 8 passed, verified) |
| Full suite command | `uv run pytest -q -ra --durations=0 -n auto --dist=loadfile` (Makefile `test`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DLS-OUTLINE-01 | `.sh` → treesitter outline, function+assignment kept, body stripped, exports kept | unit | `uv run pytest tests/core/test_shell_outline.py -q` | ✅ (extend: assert `export`/`declaration_command` kept, `command` noise dropped) |
| DLS-OUTLINE-02 | `.sql` → treesitter outline listing table/view/index/function | unit | `uv run pytest tests/core/test_sql_outline.py -q` | ❌ Wave 0 |
| DLS-OUTLINE-03 | `.yaml` → treesitter outline of top-level keys only (no nested scalars) | unit | `uv run pytest tests/core/test_yaml_outline.py -q` | ❌ Wave 0 |
| DLS-OUTLINE-04 | `.toml` → treesitter outline of table headers + top-level pairs | unit | `uv run pytest tests/core/test_toml_outline.py -q` | ❌ Wave 0 |
| DLS-OUTLINE-05 | `.json` large/nested → treesitter top-level keys; small/flat → generic (guard) | unit | `uv run pytest tests/core/test_json_outline.py -q` | ❌ Wave 0 |
| (engine) | refactored `outline_text` keeps rust/bash containers correct | unit (regression) | `uv run pytest tests/core -k outline -q` | ✅ |

**Selector sanity:** `-k outline` already matches 8 tests (verified). New files named `test_*_outline.py`
and functions named `test_<lang>_outline_*` will be picked up by the same `-k outline` selector — no
stale selector risk.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/core -k outline -q`
- **Per wave merge:** `uv run pytest tests/core -q` then `make lint typecheck`
- **Phase gate:** full suite green (`make test`) + `uv run ruff check $(PY_PATHS)` + `uv run mypy --strict $(PY_PATHS)` before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/core/test_sql_outline.py` — covers DLS-OUTLINE-02 (multi-statement fixture incl. `CREATE FUNCTION` body)
- [ ] `tests/core/test_yaml_outline.py` — covers DLS-OUTLINE-03 (nested mapping; assert top-level keys only, nested scalars absent)
- [ ] `tests/core/test_toml_outline.py` — covers DLS-OUTLINE-04 (tables + top-level pairs + `[[array]]`)
- [ ] `tests/core/test_json_outline.py` — covers DLS-OUTLINE-05 (one large-nested fixture → treesitter; one small-flat fixture → generic, asserting designed degradation)
- [ ] Extend `tests/core/test_shell_outline.py` — assert tuned bash config (export kept, command noise dropped)

No framework install needed — pytest + tree-sitter-language-pack already present.

### Plan/Wave structuring recommendation
All five languages share **one engine change** (the `unwrap`/`keep_first_line` generalization). That
engine change is a hard dependency for sql/yaml/json. Recommended structure:

- **Plan 17-01 (engine + low-risk languages):** Add `unwrap`/`keep_first_line` to `LangCfg`, refactor
  `outline_text` to the recursive `visit()` (backward-compatible), tune **bash**, add **toml**. Ship
  with the existing rust/shell regression tests + new toml/bash tests. These two need no descent depth >0
  beyond toml's zero-depth, so they validate the engine cheaply.
- **Plan 17-02 (descend-dependent languages, blocked on 17-01):** Add **sql**, **yaml**, **json**
  configs + their fixture tests. These exercise the `unwrap` recursion (1-level SQL/JSON, 3-level YAML)
  and the guard-driven degradation for JSON.

Two plans, two waves (17-02 blocked on 17-01) is the natural split because the engine refactor must land
and prove backward-compat before the descend-dependent languages build on it. A single plan is viable
under `standard` granularity but the wave split de-risks the engine refactor.

## Code Examples

### Verified probe to confirm a grammar + dump node kinds (reusable during impl)
```python
# Source: verified live this session (2026-05-29). MUST use _node_attr (methods, not attrs).
from tree_sitter_language_pack import get_parser
from atelier.core.capabilities.semantic_file_memory.treesitter_ast import (
    _node_attr, _children, _kind, _byte_range,
)
p = get_parser("yaml")           # raises if grammar missing → that language stays generic
tree = p.parse(source_str)       # NOTE: str, not bytes
root = _node_attr(tree, "root_node")
for c in _children(root):
    print(_kind(c), source_str[slice(*_byte_range(c))].splitlines()[0])
```

### Test skeleton (mirrors existing `test_rust_outline.py` style)
```python
# tests/core/test_yaml_outline.py
from pathlib import Path
from atelier.core.capabilities.semantic_file_memory import SemanticFileMemoryCapability

def test_yaml_outline_keeps_top_level_keys_only(tmp_path: Path) -> None:
    source = (
        "name: ci\n"
        "on:\n  push:\n    branches: [main]\n"
        "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make test\n"
        "version: 1\n"
    )
    path = tmp_path / "ci.yaml"
    path.write_text(source, encoding="utf-8")
    payload = SemanticFileMemoryCapability(tmp_path).smart_read(path, expand=False, outline_threshold=0)
    assert payload["mode"] == "outline"
    outline = payload["outline"]
    assert outline["kind"] == "treesitter"
    text = outline["text"]
    assert "name:" in text and "jobs:" in text and "version:" in text
    assert "runs-on" not in text   # nested scalar excluded (top-level only)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Generic regex outline for shell/sql/yaml/toml/json | Dedicated tree-sitter `LangCfg` entries | Phase 17 (this) | Structure-aware, smaller, schema-at-a-glance for SQL; top-level keys for data files |
| `outline_text` inspects root's direct children only | Recursive descent through declared `unwrap` wrapper kinds | Phase 17 (this) | Unlocks SQL/YAML/JSON whose declarations are nested in wrappers |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Header-only SQL outline (trim `column_definitions`/`function_body`) satisfies DLS-OUTLINE-02 "schema-level constructs" | Phase Requirements / configs | If reviewers want full column lists, swap `create_table` from `keep_signature` to `keep_full` — but then dense DDL may not clear the 25% guard (falls to generic, still acceptable per SC5) |
| A2 | Two-plan split (engine+bash+toml, then sql+yaml+json) is the right granularity | Validation Architecture | Low — a single plan is also viable under `standard` granularity; this is a structuring preference, not a correctness claim |

**All factual node-kind, parser-availability, savings-ratio, and binding-behavior claims in this document
are `[VERIFIED: live uv run probe, 2026-05-29]`, not assumed.**

## Open Questions

All resolvable by implementation/probing — **none require user input**:

1. **Exact SQL body-trim node kinds for clean headers across dialects.**
   - What we know: `column_definitions`, `function_body`, `create_query` (view), `index_fields` (index) verified for the default SQL dialect.
   - What's unclear: `tree-sitter-language-pack`'s `sql` grammar dialect coverage for `CREATE PROCEDURE`, `CREATE TRIGGER`, vendor-specific DDL.
   - Recommendation: during impl, probe additional DDL fixtures; add any extra body kinds to `body_kinds`. Unknown statements simply pass through `unwrap` and either match `keep_signature` or are skipped — no crash.

2. **`{ ... }` marker cosmetics for data languages.**
   - What we know: `_signature_slice` appends `" { ... }"` when it trims at a body. For SQL/TOML headers this reads slightly oddly (`CREATE TABLE users { ... }`).
   - Recommendation: acceptable as-is; if undesirable, make the marker configurable per `LangCfg` or use `keep_first_line` for those kinds. Cosmetic only — does not affect savings or correctness.

3. **JSON guard-clearance threshold in practice.**
   - What we know: small/flat JSON (90%) correctly stays generic; deeply nested config clears.
   - Recommendation: ship one large-nested + one small-flat fixture to lock in both branches; no tuning needed.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `tree-sitter-language-pack` | all 5 outlines | ✓ | 1.8.1 | — (per-language `get_parser` failure → that language stays on generic path) |
| `tree-sitter` runtime | parsing | ✓ | ≥0.23 | — |
| `bash` grammar | DLS-OUTLINE-01 | ✓ | bundled | generic regex |
| `sql` grammar | DLS-OUTLINE-02 | ✓ | bundled | generic regex |
| `yaml` grammar | DLS-OUTLINE-03 | ✓ | bundled | generic regex |
| `toml` grammar | DLS-OUTLINE-04 | ✓ | bundled | generic regex |
| `json` grammar | DLS-OUTLINE-05 | ✓ | bundled | generic regex |
| `pytest` / `ruff` / `mypy` | validation | ✓ | via `uv` | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — all 5 grammars verified present.

## Sources

### Primary (HIGH confidence)
- Live `uv run` probes against installed `tree-sitter-language-pack` 1.8.1 (2026-05-29): parser
  availability, full node-kind trees for bash/sql/yaml/toml/json, prototype outline outputs + savings ratios.
- `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` — current engine, `LangCfg`, `_node_attr` helpers.
- `src/atelier/core/capabilities/semantic_file_memory/capability.py` (lines 312–376) — outline ordering and 25% guard.
- `src/atelier/infra/code_intel/languages.py` — canonical registry (Phase 16); bash/sql/yaml/toml/json present.
- `.planning/phases/16-canonical-language-registry/16-VERIFICATION.md` — Phase 16 wiring verified.
- `docs/plans/dedicated-language-support/M2-treesitter-coverage.md` — source design intent.
- `Makefile` (lint=`ruff check`, typecheck=`mypy --strict`, test=`pytest -n auto`), `pyproject.toml` (deps).

### Secondary / Tertiary
- None required — all claims verified against primary sources/tools.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all grammars verified installed and parsing.
- Architecture (engine enhancement): HIGH — wrapper chains verified live; recursive `visit()` prototype produced correct outlines for all 5 languages.
- Pitfalls: HIGH — savings ratios and guard pass/fail verified empirically (bash 50%, sql 67%, yaml 18%, toml 43%, json 90%).

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (stable — internal engine + bundled grammars; only `tree-sitter-language-pack` upgrades could shift node kinds)
