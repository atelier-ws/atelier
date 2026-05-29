# Phase 16: Canonical Language Registry - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 8 (1 new module, 4 modified surfaces, 3 test files)
**Analogs found:** 8 / 8

This is a **pure refactor / consolidation phase**. Every "new" file has a strong
in-repo analog because the registry is built by *unifying* code that already
exists in four surfaces. Prefer copying from the real surfaces below over the
RESEARCH.md sketches — the surfaces carry the exact extension coverage,
behavior, and signatures that must be preserved.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/atelier/infra/code_intel/languages.py` (new) | utility (data registry) | transform (lookup) | `src/atelier/infra/code_intel/scip/binaries.py` (frozen-data + lookup) + `tags.py::Tag` dataclass | role-match (no exact registry exists; assembled from 4 surfaces) |
| `src/atelier/core/capabilities/semantic_file_memory/capability.py` (modify `_language_for`) | service | transform | itself (L80-122, the buggy map being replaced) | exact (in-place migration) |
| `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` (verify keys + derive `SUPPORTED_LANGUAGES`) | config | transform | itself (L52-300) | exact |
| `src/atelier/infra/tree_sitter/tags.py` (modify `detect_language`) | service | transform | itself (L82-91) | exact |
| `src/atelier/infra/code_intel/scip/binaries.py` (re-key `_SCIP_BINARIES`) | config | transform | itself (L9-13) | exact |
| `tests/infra/code_intel/test_languages.py` (new) | test | request-response | `tests/infra/code_intel/scip/test_scip_adapter.py` (pkg layout) | role-match |
| `tests/core/test_shell_outline.py` (new) | test | request-response | `tests/core/test_rust_outline.py` | exact (mirror structure) |
| `tests/infra/code_intel/__init__.py` + `scip/__init__.py` (new) | test scaffold | — | `tests/infra/__init__.py`, `tests/core/__init__.py` | exact |

**Reference implementation (NOT in scope, but copy its spellings):**
`src/atelier/core/capabilities/tool_supervision/search_read.py::_LANG_MAP` (L84-108)
already uses the correct canonical names (`bash`, `csharp`). It is the de-facto
correct table. Seed the registry's extension coverage as the **union** of
`capability.py::_language_for` and this map. Do NOT modify search_read.py in
this phase (out of locked scope).

## Pattern Assignments

### `src/atelier/infra/code_intel/languages.py` (new — utility / data registry)

**Analog:** `src/atelier/infra/code_intel/scip/binaries.py` (module-level frozen
table + pure lookup function + `__all__`); `tags.py::Tag` (frozen dataclass
convention).

**Module header + imports pattern** (copy from `binaries.py` L1-7 and
`tags.py` L1-9 — note both use `from __future__ import annotations` and stdlib
only, which keeps this a cycle-free leaf module):
```python
"""Canonical language registry — single source of truth for language identity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
```
Registry MUST import nothing from `atelier.core` (Pitfall 1 — import cycle).
Stdlib only.

**Frozen dataclass pattern** (copy convention from `tags.py` L14-20 and
`treesitter_ast.py` L33-49 — both use `@dataclass(frozen=True)`):
```python
@dataclass(frozen=True)
class Language:
    name: str                   # canonical key == tree-sitter-language-pack parser name
    extensions: frozenset[str]  # incl. leading dot, lowercase
    parser_name: str            # tree-sitter-language-pack key (usually == name)
    scip_indexer: str | None    # e.g. "scip-python"; None if no indexer
```

**Module-level table + derived indices** (copy the "table then comprehension"
shape from `binaries.py` L9-13 `_SCIP_BINARIES` and `treesitter_ast.py` L300
`SUPPORTED_LANGUAGES = frozenset(_LANG_CONFIG.keys())`):
```python
LANGUAGES: tuple[Language, ...] = (
    Language("python",     frozenset({".py", ".pyi"}),                 "python",     "scip-python"),
    Language("typescript", frozenset({".ts", ".tsx"}),                 "typescript", "scip-typescript"),
    Language("javascript", frozenset({".js", ".jsx", ".mjs", ".cjs"}), "javascript", "scip-typescript"),
    Language("bash",       frozenset({".sh", ".bash", ".zsh"}),        "bash",       None),
    Language("csharp",     frozenset({".cs"}),                         "csharp",     None),
    # go, rust, java, kotlin (.kt/.kts), scala, ruby, cpp (.cpp/.cc/.cxx/.hpp/.hh),
    # c (.c/.h), swift, php, sql, markdown (.md/.markdown), yaml (.yaml/.yml),
    # toml, json  — seed scip_indexer=None for all of these (Phase 19 fills them)
)

EXTENSION_TO_LANGUAGE: dict[str, Language] = {
    ext: lang for lang in LANGUAGES for ext in lang.extensions
}
_BY_NAME: dict[str, Language] = {lang.name: lang for lang in LANGUAGES}
ALL_LANGUAGES: frozenset[str] = frozenset(_BY_NAME)
```
**Extension coverage = UNION of `capability.py::_language_for` (L83-122) and
`search_read.py::_LANG_MAP` (L84-108).** Dropping any extension is a regression
(Pitfall 3). `.sh/.bash/.zsh` MUST point at the `bash` Language (canonicalizes
shell→bash at the data layer, not a separate alias map — Pattern 2).

**Lookup functions** (mirror `binaries.py::discover_scip_binary` L16 signature
style — single `Path`-typed arg, `dict.get`):
```python
def language_for_path(path: str | Path) -> Language | None:
    return EXTENSION_TO_LANGUAGE.get(Path(path).suffix.lower())

def language_by_name(name: str) -> Language | None:
    return _BY_NAME.get(name)
```
Note `.suffix.lower()` matches the existing normalization in
`capability.py:82` and `search_read.py::_detect_lang`.

**Public surface** (copy `__all__` convention from `binaries.py` L44,
`tags.py` L117):
```python
__all__ = [
    "Language", "LANGUAGES", "EXTENSION_TO_LANGUAGE", "ALL_LANGUAGES",
    "language_for_path", "language_by_name",
]
```

---

### `src/atelier/core/capabilities/semantic_file_memory/capability.py` (modify `_language_for`)

**Analog:** itself, L80-122 (the map being deleted).

**Current (L80-122)** — a 40-line hardcoded dict with the bug at L115-117
(`.sh/.bash/.zsh → "shell"`). Replace the entire method body with a delegation
that preserves the `"text"` fallback and the `@staticmethod` decorator:
```python
from atelier.infra.code_intel.languages import language_for_path

@staticmethod
def _language_for(path: Path) -> str:
    lang = language_for_path(path)
    return lang.name if lang is not None else "text"
```
- Keep the return type `str` (callers at L318, L431 consume a string — VERIFIED).
- The `shell → bash` fix happens for free: registry maps `.sh` → `Language("bash")`.
- **Delete the stale comment** at L95-97 referencing
  `docs/plans/active/savings-honest-ab/README.md` (RESEARCH "Deprecated").
- Import placement: top-of-file import block (L12-18 already imports sibling
  modules with relative paths; the registry is infra, so use the absolute
  `from atelier.infra.code_intel.languages import language_for_path`).

**Downstream behavior to verify (no edit, just confirm):** outline branch at
L363-385 gates on `language in SUPPORTED_LANGUAGES`. Once `_language_for`
returns `"bash"`, `.sh` files reach the tree-sitter branch because `"bash"` is
already a `_LANG_CONFIG` key (treesitter_ast.py:291). This is the payoff.

---

### `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` (verify keys + keep `SUPPORTED_LANGUAGES` derived)

**Analog:** itself, L52-300.

**No key renames needed.** `_LANG_CONFIG` keys are already canonical (`bash` at
L291, `csharp`/`go`/`rust` etc.). The derivation at L300 stays:
```python
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(_LANG_CONFIG.keys())
```
**Required action:** add a *test-only* invariant (no source change) asserting
every `_LANG_CONFIG` key resolves via `language_by_name(...)` (Pitfall 2). If a
key ever fails to resolve, that's the drift the registry exists to prevent.
Do NOT rename the `csharp` key (Anti-Pattern, RESEARCH L217-219).

**Parser-load graceful-degradation pattern to preserve** (L303-313): the
existing `_get_parser` already catches missing grammars and returns `None`. Do
not add a new "is this a real grammar" check (Don't Hand-Roll).

---

### `src/atelier/infra/tree_sitter/tags.py` (modify `detect_language`)

**Analog:** itself, L82-91.

**Current (L82-91)** — 7-extension dict returning `str | None` (note: uses
`path.suffix` WITHOUT `.lower()`, unlike capability.py). Replace with
delegation, preserving the `str | None` return type that `extract_tags_from_text`
(L98-106) depends on:
```python
from atelier.infra.code_intel.languages import language_for_path

def detect_language(path: Path) -> str | None:
    lang = language_for_path(path)
    return lang.name if lang is not None else None
```
- Return `None` (not `"text"`) — caller L99-100 short-circuits to `[]` on `None`.
- **Behavior widening note:** broadening detection means more languages reach
  `_regex_tags` (L46-79), which only has patterns for js/ts/go/rust and falls
  back to `patterns["javascript"]` (L53). This is acceptable for Phase 16
  (tree-sitter tagging is Phase 18); confirm no crash via test. The default
  pattern handles unknown languages safely.
- Keep `__all__` (L117) and the `_python_tags` AST path (L101-103) unchanged.

---

### `src/atelier/infra/code_intel/scip/binaries.py` (re-key `_SCIP_BINARIES` to canonical)

**Analog:** itself, L9-44.

**Current (L9-13)** keys are already canonical (`python`, `typescript`,
`javascript`). The migration sources the env-var/fallback from the registry's
`scip_indexer` field rather than a local dict, **without changing env-var names**:
```python
from atelier.infra.code_intel.languages import language_by_name

def discover_scip_binary(language: str) -> Path | None:
    lang = language_by_name(language)
    indexer = lang.scip_indexer if lang else None
    if indexer is None:
        return None
    # env-var name MUST stay derived/preserved as today:
    #   python     -> ATELIER_SCIP_PYTHON_BIN
    #   typescript -> ATELIER_SCIP_TYPESCRIPT_BIN
    #   javascript -> ATELIER_SCIP_TYPESCRIPT_BIN
    ...
```
**Critical constraints (VERIFIED, RESEARCH L242, L328-330):**
- Env-var names `ATELIER_SCIP_PYTHON_BIN` / `ATELIER_SCIP_TYPESCRIPT_BIN` MUST be
  byte-identical after migration (external config depends on them). Since
  re-keying loses the env-var string, either keep a minimal `_SCIP_BINARIES`
  env-var map *keyed on canonical name* OR derive the env-var as
  `f"ATELIER_SCIP_{indexer.upper()...}"` — prefer keeping the explicit env-var
  map (least risk; the dict is already canonical-keyed).
- Keep the discovery resolution loop (L20-30: `shutil.which` → `is_file` →
  `os.access X_OK`) byte-identical.
- Keep `discover_scip_binaries()` (L33-41) iterating exactly `("python",
  "typescript")` for Phase 16. Expansion to go/rust/java/etc. is Phase 19.
- Keep `__all__` (L44).

**Recommendation:** the lowest-risk migration keeps the local env-var map but
adds a test asserting registry `scip_indexer` agrees with it. Full registry
sourcing is safe to defer to Phase 19 if it risks the env-var contract.

---

### `tests/infra/code_intel/test_languages.py` (new — registry unit tests)

**Analog:** `tests/infra/code_intel/scip/test_scip_adapter.py` (module layout,
import style, pytest conventions).

**Imports pattern** (copy from test_scip_adapter.py L1-12 style):
```python
from __future__ import annotations

from atelier.infra.code_intel.languages import (
    ALL_LANGUAGES, EXTENSION_TO_LANGUAGE, Language,
    language_by_name, language_for_path,
)
```

**Test coverage required (DLS-LANG-01/02/03/04):**
- Registry exposes `Language`, `language_for_path`, `language_by_name`,
  `EXTENSION_TO_LANGUAGE`, `ALL_LANGUAGES` (DLS-LANG-01).
- Every extension in the OLD `capability.py::_language_for` map resolves via
  `language_for_path` to the same name — EXCEPT `.sh/.bash/.zsh` which now
  resolve to `"bash"` (was `"shell"`) (DLS-LANG-02/03). Parametrize over the
  old map.
- Unknown extension (e.g. `.xyz`) → `language_for_path` returns `None`;
  the `capability._language_for` wrapper returns `"text"` (DLS-LANG-02).
- `csharp` is canonical (NOT `c_sharp`) (DLS-LANG-04).
- **Cross-surface invariant:** every key in
  `treesitter_ast._LANG_CONFIG` resolves via `language_by_name(...)`
  (Pitfall 2 guard, DLS-LANG-04). Import `_LANG_CONFIG` and assert.

**Scaffold:** create empty `tests/infra/code_intel/__init__.py` and
`tests/infra/code_intel/scip/__init__.py` — they do NOT currently exist
(VERIFIED) and the package path needs them, mirroring `tests/infra/__init__.py`.

---

### `tests/core/test_shell_outline.py` (new — regression: `.sh` → treesitter)

**Analog:** `tests/core/test_rust_outline.py` — copy its exact structure.

**Full pattern to mirror** (test_rust_outline.py L1-33):
```python
from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.semantic_file_memory import SemanticFileMemoryCapability


def test_shell_outline_uses_treesitter(tmp_path: Path) -> None:
    source = """
greeting="hello"

run_build() {
    local sentinel_body=42
    echo "$sentinel_body"
}
""".strip()
    path = tmp_path / "sample.sh"
    path.write_text(source, encoding="utf-8")

    cap = SemanticFileMemoryCapability(tmp_path)
    payload = cap.smart_read(path, expand=False, outline_threshold=0)

    assert payload["language"] == "bash"          # DLS-LANG-03: shell→bash
    assert payload["mode"] == "outline"
    outline = payload["outline"]
    assert isinstance(outline, dict)
    assert outline["kind"] == "treesitter"        # NOT "generic" (the bug fix)
    assert "run_build" in outline["text"]
    assert "sentinel_body" not in outline["text"] # body stripped (signature-only)
```
Key assertions: `language == "bash"` and `outline["kind"] == "treesitter"`
(was `"generic"` before the fix). The `expand=False, outline_threshold=0`
invocation is the same one test_rust_outline.py uses to force the outline path.

## Shared Patterns

### Frozen-data + pure-lookup module (cycle-free leaf)
**Source:** `src/atelier/infra/code_intel/scip/binaries.py` (L9-44),
`src/atelier/infra/tree_sitter/tags.py::Tag` (L14-20)
**Apply to:** the new `languages.py`
- `from __future__ import annotations` + stdlib-only imports.
- Module-level immutable table (`tuple`/`dict`), derived indices via
  comprehension at import time, `@dataclass(frozen=True)` records.
- Pure functions taking `str | Path`, returning `Optional`, using `dict.get`.
- Explicit `__all__`. No `core` imports (avoids Pitfall 1 cycle).

### Boundary delegation preserving public signatures
**Source:** RESEARCH Pattern 2; applied at `capability.py:_language_for`,
`tags.py:detect_language`, `binaries.py:discover_scip_binary`
**Apply to:** all four modified surfaces
- Replace the local dict body with `language_for_path(...)` / `language_by_name(...)`.
- Map the registry's `None` back to each surface's existing sentinel:
  `capability.py` → `"text"`, `tags.py` → `None`.
- Return type stays a **language string** (or `str | None`); only the source
  of the string changes. Callers are untouched.

### Outline-path test invocation
**Source:** `tests/core/test_rust_outline.py` (L20-23),
`tests/core/test_python_outline.py`, `tests/core/test_typescript_outline.py`
**Apply to:** `tests/core/test_shell_outline.py`
- `cap = SemanticFileMemoryCapability(tmp_path)` then
  `cap.smart_read(path, expand=False, outline_threshold=0)`.
- Assert `payload["mode"] == "outline"`, inspect `payload["outline"]["text"]`,
  use a `sentinel_body` token to prove bodies are stripped.

### "shell" tool vs "shell" language — DO NOT TOUCH
**Source:** RESEARCH Pitfall 4 / Anti-Patterns (25+ unrelated refs)
**Apply to:** all edits
- Never global-replace `"shell"`. The bash-exec *tool* named `"shell"` lives in
  `mcp_server.py`, `router.py`, `api.py`, `plugin_runtime.py`, `environment.py`,
  session parsers, benchmarks. Scope edits strictly to the four code-intel
  surfaces above.

## No Analog Found

None. Every file has an in-repo analog (this is a consolidation phase). The
closest thing to "no analog" is the `Language` registry module itself, but its
shape is fully covered by `binaries.py` (frozen table + lookup) + `tags.py`
(frozen dataclass) + `treesitter_ast.py` (`SUPPORTED_LANGUAGES` derived-index
pattern). The reference table `search_read.py::_LANG_MAP` provides the correct
canonical spellings to seed it.

## Metadata

**Analog search scope:** `src/atelier/infra/code_intel/`,
`src/atelier/infra/tree_sitter/`,
`src/atelier/core/capabilities/semantic_file_memory/`,
`src/atelier/core/capabilities/tool_supervision/`, `tests/infra/`, `tests/core/`
**Files scanned:** 7 source + 3 test files read; directory listings for
`tests/infra/code_intel/`, `src/atelier/infra/code_intel/`
**Pattern extraction date:** 2026-05-29
