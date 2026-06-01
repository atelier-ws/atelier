# Phase 17: Tree-sitter Outline Coverage - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 6 (1 engine module modified, 1 registry consumed read-only, 4–5 test files)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` (modify: `LangCfg` + `outline_text` + 5 `_LANG_CONFIG` entries) | engine + config table | transform (AST → text outline) | itself — existing `rust`/`bash` entries + flat root loop | exact (extend in place) |
| `tests/core/test_shell_outline.py` (tune assertions for retuned bash cfg) | test | request-response (smart_read) | `tests/core/test_shell_outline.py` (self) | exact |
| `tests/core/test_sql_outline.py` (new) | test | request-response | `tests/core/test_rust_outline.py` | exact (container/signature outline) |
| `tests/core/test_yaml_outline.py` (new) | test | request-response | `tests/core/test_shell_outline.py` | exact (treesitter-kind assertion) |
| `tests/core/test_toml_outline.py` (new) | test | request-response | `tests/core/test_shell_outline.py` | exact |
| `tests/core/test_json_outline.py` (new) | test | request-response | `tests/core/test_shell_outline.py` | exact (incl. guard-fallback case) |

**Scope guard:** Only `treesitter_ast.py` and `tests/core/*_outline.py` change. `capability.py` and
`languages.py` are **read-only** in Phase 17 — they were finalized in Phase 16 and already wire the
path correctly. Do **not** plan repo-map tags or SCIP (Phases 18–20).

## Pattern Assignments

### `treesitter_ast.py` — `LangCfg` dataclass (engine, transform)

**Analog:** the existing `LangCfg` definition (same file, lines 33–49).

**Pattern — backward-compatible field addition** (mirror existing `field(default_factory=frozenset)`):
```python
@dataclass(frozen=True)
class LangCfg:
    keep_full: frozenset[str] = field(default_factory=frozenset)
    keep_signature: frozenset[str] = field(default_factory=frozenset)
    container: frozenset[str] = field(default_factory=frozenset)
    member: frozenset[str] = field(default_factory=frozenset)
    body_kinds: frozenset[str] = field(default_factory=frozenset)
    parser_name: str = ""
    # NEW (Phase 17) — append at end, defaulted to empty so all 12 existing
    # configs are byte-for-byte unchanged in behavior:
    unwrap: frozenset[str] = field(default_factory=frozenset)         # transparent descend
    keep_first_line: frozenset[str] = field(default_factory=frozenset) # data key/value emit
```
**Why this exact shape:** `frozen=True` + `field(default_factory=frozenset)` is the established
convention (lines 33, 39–47). New fields MUST default to empty frozensets and be **appended** so the
12 existing entries (`go`, `rust`, `java`, `ruby`, `c`, `cpp`, `csharp`, `kotlin`, `php`, `swift`,
`scala`, `bash`) keep empty `unwrap`/`keep_first_line` and collapse to today's flat behavior.

---

### `treesitter_ast.py` — `outline_text` engine refactor (engine, transform)

**Analog:** the existing flat root-children loop (same file, lines 397–413).

**THE ROOT-CHILD-ONLY LIMITATION (critical):** the current engine only inspects **direct children of
the root node** (line 399: `for child in _children(root):`). This works for bash/toml (declarations
sit at top level) but returns `None` for **sql / yaml / json**, whose structure is buried in
transparent wrapper nodes:
- **SQL:** `program → statement → create_table | create_view | create_index | create_function | alter_table`
- **YAML:** `stream → document → block_node → block_mapping → block_mapping_pair`
- **JSON:** `document → object → pair`

**Required change — recursive `visit()` that descends only `unwrap` kinds:**
```python
# Refactor the lines 397-413 flat loop into a nested recursive walk.
root = _node_attr(tree, "root_node")
pieces: list[bytes] = []

def visit(node: Any) -> None:
    for child in _children(node):
        kind = _kind(child)
        if kind in cfg.unwrap:                       # NEW: transparent descend (recurse)
            visit(child)
        elif kind in cfg.keep_full:
            start, end = _byte_range(child)
            pieces.append(source_bytes[start:end].rstrip())
        elif kind in cfg.keep_signature:
            pieces.append(_signature_slice(source_bytes, child, cfg.body_kinds))
        elif kind in cfg.keep_first_line:            # NEW: first-line emit for data langs
            start, end = _byte_range(child)
            text = source_bytes[start:end].decode("utf-8", errors="replace")
            pieces.append(text.splitlines()[0].rstrip().encode("utf-8") if text else b"")
        elif kind in cfg.container:
            pieces.append(_signature_slice(source_bytes, child, cfg.body_kinds))
            pieces.extend(_extract_member_signatures(child, source_bytes, cfg))
        # else: skip — and crucially do NOT recurse (preserves top-level-only output)

visit(root)
if not pieces:
    return None
return b"\n".join(pieces).decode("utf-8", errors="replace")
```
**Reuse existing helpers verbatim** — do not reimplement: `_children` (line 326), `_byte_range`
(line 331), `_kind` (line 338), `_signature_slice` (line 342), `_extract_member_signatures` (line 352),
`_node_attr` (line 316). The binding exposes attributes **as methods**; only `_node_attr` handles that
duality — never use bare `getattr(node, "type")`.

**Backward-compat invariant:** with empty `unwrap`/`keep_first_line`, `visit(root)` is exactly the old
flat loop over root children. The 8 existing outline tests (incl. rust/shell) MUST stay green.

---

### `treesitter_ast.py` — 5 `_LANG_CONFIG` entries (config table)

**Analog:** existing entries — `rust` (lines 66–82) for container/signature style, `bash` (lines
291–295) for the entry being retuned.

**Entries to add/tune** (node kinds VERIFIED live against `tree-sitter-language-pack` 1.8.1 — see
RESEARCH §"Recommended `_LANG_CONFIG` entries"):
```python
"bash": LangCfg(   # TUNE existing line 291: drop noisy command/comment, add declaration_command
    keep_full=frozenset({"variable_assignment", "declaration_command"}),
    keep_signature=frozenset({"function_definition"}),
    body_kinds=frozenset({"compound_statement"}),
),  # ~50% of source — clears 25% guard
"sql": LangCfg(    # NEW
    unwrap=frozenset({"statement"}),
    keep_signature=frozenset({"create_table", "create_view", "create_index",
                              "create_function", "alter_table"}),
    body_kinds=frozenset({"column_definitions", "function_body", "create_query", "index_fields"}),
),  # ~67% — clears guard
"yaml": LangCfg(   # NEW
    unwrap=frozenset({"stream", "document", "block_node", "block_mapping"}),
    keep_first_line=frozenset({"block_mapping_pair"}),
),  # ~18% — strong win
"toml": LangCfg(   # NEW — works with existing engine (top-level children); keep_first_line for headers
    keep_full=frozenset({"pair"}),
    keep_first_line=frozenset({"table", "table_array_element"}),
),  # ~43%
"json": LangCfg(   # NEW — low value, intentionally guard-gated
    unwrap=frozenset({"document", "object"}),
    keep_first_line=frozenset({"pair"}),
),  # small/flat JSON correctly rejected by 25% guard → generic path (designed behavior)
```
`SUPPORTED_LANGUAGES` (line 300) auto-derives from `_LANG_CONFIG.keys()` — no separate edit needed.
All keys (`bash`/`sql`/`yaml`/`toml`/`json`) already resolve via `languages.py` `language_by_name`
(verified: registry lines 44, 57, 59–61) — **do not add any extension/parser map**.

---

### Test files (test, request-response via `smart_read`)

**Two analog shapes — pick per language:**

**Shape A — full-pipeline `smart_read` test** (use for ALL Phase 17 tests). Analog:
`tests/core/test_shell_outline.py` lines 1–45.
```python
from __future__ import annotations
from pathlib import Path
from atelier.core.capabilities.semantic_file_memory import SemanticFileMemoryCapability

def test_<lang>_outline_reaches_treesitter(tmp_path: Path) -> None:
    source = """<representative fixture>""".strip()
    path = tmp_path / "sample.<ext>"
    path.write_text(source, encoding="utf-8")

    cap = SemanticFileMemoryCapability(tmp_path)
    payload = cap.smart_read(path, expand=False, outline_threshold=0)

    assert payload["language"] == "<canonical-name>"
    assert payload["mode"] == "outline"
    outline = payload["outline"]
    assert isinstance(outline, dict)
    assert outline["kind"] == "treesitter"          # NOT generic — the payoff
    text = outline["text"]
    assert "<expected top-level symbol/key>" in text
    assert "<body/nested token>" not in text         # body/nesting stripped
```
**Key conventions copied from analogs:** `outline_threshold=0` forces the outline branch (shell test
line 30); `payload["mode"] == "outline"`, `outline["kind"] == "treesitter"`, positive assertion on a
kept symbol + negative assertion on a stripped body token (rust test lines 30–32, shell lines 43–45).

**Per-language fixtures & assertions:**
- `test_sql_outline.py` — fixture with `CREATE TABLE`/`CREATE VIEW`/`CREATE INDEX`/`CREATE FUNCTION`;
  assert all 4 construct names present, function body line absent. (Mirror rust container test.)
- `test_yaml_outline.py` — fixture with top-level `name:`/`on:`/`jobs:` + nested mappings; assert
  top-level keys present, deeply-nested scalar value absent.
- `test_toml_outline.py` — fixture with `[package]`/`[[bin]]` + top-level pairs; assert headers + pairs
  present, nested table values absent.
- `test_json_outline.py` — TWO tests: (1) large/nested JSON → `kind == "treesitter"`; (2) small/flat
  JSON → `kind == "generic"` or `mode == "full"` (guard correctly rejects). This documents
  DLS-OUTLINE-05 degradation as intended behavior.
- `test_shell_outline.py` — update existing assertions if retuned bash cfg changes what is kept
  (e.g. `declaration_command` now surfaces `export`/`declare` lines).

## Shared Patterns

### 25% Savings Guard (DO NOT TOUCH — orchestration authority)
**Source:** `capability.py` `smart_read`, tree-sitter branch lines 334–352 (esp. the guard
`len(ts_text) <= int(len(source) * 0.75)` at line 340) and generic branch lines 357–367.
**Apply to:** all Phase 17 work — **by leaving it alone.** The guard already protects against shipping
a "dedicated" outline that isn't ≥25% smaller; it degrades cleanly to generic/full. Phase 17 adds
configs and engine logic only; it must **never** duplicate, relocate, or weaken this guard, and must
never add a competing guard inside `outline_text`.
```python
# capability.py:338-352 (read-only reference)
if language in SUPPORTED_LANGUAGES:
    ts_text = ts_outline_text(language, source)
    if ts_text and len(ts_text) <= int(len(source) * 0.75):   # the single authority
        result.update({"mode": "outline",
                       "outline": {"kind": "treesitter", "language": language, "text": ts_text},
                       "tokens_saved": self._token_savings(source, ts_text)})
        return result
# else: falls through to generic regex outline (same guard) then full file
```

### Language Registry (consume, never fork)
**Source:** `infra/code_intel/languages.py` — `language_for_path` (line 74), `language_by_name`
(line 83), `LANGUAGES` table (lines 34–62).
**Apply to:** every `_LANG_CONFIG` key. All Phase 17 keys already exist in the registry (bash 44,
sql 57, yaml 59, toml 60, json 61). Registry drift (adding ext/parser maps elsewhere) is a STATE
watch-point violation — forbidden.

### Method-vs-value binding helper
**Source:** `treesitter_ast.py` `_node_attr` (line 316).
**Apply to:** any node-attribute access in the engine refactor. The language-pack binding exposes
`root_node`/`child_count`/`start_byte`/`kind` as callables; only `_node_attr` normalizes this.

## No Analog Found

None. Every Phase 17 file extends an existing module or mirrors an existing outline test. The only
genuinely new mechanisms (`unwrap` descent, `keep_first_line` emit) live inside the existing
`outline_text` engine and are prototyped/verified in RESEARCH.md §Pattern 1 & §Pattern 2.

## Risks & Anti-Patterns to Avoid

| Risk / Anti-pattern | Why it's wrong | Correct pattern |
|---------------------|----------------|-----------------|
| Putting `statement`/`object` in `keep_full` to "make SQL/JSON work" | Keeps entire bodies, blows the 25% guard, emits noise | Use `unwrap` to descend transparently |
| Recursing into **kept** nodes | Explodes YAML/JSON to every nested key | Only `unwrap` kinds recurse; kept nodes terminate |
| Weakening / relocating / duplicating the 25% guard | The `capability.smart_read` guard is the single authority preventing fake savings | Leave `capability.py` untouched; let it gate |
| Adding extension/parser maps outside `languages.py` | Registry drift (STATE watch point) | Consume `language_by_name`; keys already exist |
| Inserting new `LangCfg` fields in the middle / not defaulting them | Breaks 12 existing frozen configs & their tests | Append fields, default to empty frozenset |
| Bypassing `_node_attr` with bare `getattr(node, "type")` | Binding exposes attrs as methods → returns bound method, not value | Always go through `_node_attr` |
| Broadening into repo-map tags or SCIP | Out of Phase 17 scope (Phases 18–20) | Stop at outline engine + tests |
| Hand-rolling regex structural extraction for the 5 langs | That's the generic fallback we're trying to beat | Use the tree-sitter grammars (already installed) |
| Forcing JSON to always emit treesitter | Small/flat JSON legitimately fails the guard | Let it fall to generic/full — designed (DLS-OUTLINE-05) |

## Metadata

**Analog search scope:** `src/atelier/core/capabilities/semantic_file_memory/`,
`src/atelier/infra/code_intel/`, `tests/core/`
**Files scanned:** treesitter_ast.py, capability.py, languages.py, test_shell_outline.py,
test_rust_outline.py, test_python_outline.py, test_typescript_outline.py
**Pattern extraction date:** 2026-05-29
