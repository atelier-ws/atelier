# Phase 16: Canonical Language Registry - Research

**Researched:** 2026-05-29
**Domain:** Internal code-intel refactor — language identity unification (Python)
**Confidence:** HIGH

## Summary

Phase 16 introduces a single canonical language registry
(`src/atelier/infra/code_intel/languages.py`) that becomes the source of truth
for language identity across four code-intel surfaces that today each hard-code
their own extension→language and language-name spellings. The concrete payoff is
fixing the **shell/bash drift bug**: `_language_for` in
`semantic_file_memory/capability.py` returns `"shell"` for `.sh/.bash/.zsh`, but
the tree-sitter outline config (`treesitter_ast.py::_LANG_CONFIG`) keys the
grammar under `"bash"`. Because `"shell" not in SUPPORTED_LANGUAGES`, every shell
file silently falls through to the generic regex outline and the bundled bash
grammar is dead code for real files. [VERIFIED: codebase grep — capability.py:115-117 vs treesitter_ast.py:291,300]

This is a **pure refactor / consolidation phase**, not a greenfield build. No new
external dependencies are required — `tree-sitter-language-pack` 1.8.1 is already
a project dependency and its parser names are the canonical key set the plan
mandates. I verified empirically that the canonical names `bash`, `csharp`,
`sql`, `yaml`, `toml`, `json` all load via `get_parser(...)` on the installed
version. C# canonical spelling is **`csharp`** (not `c_sharp`), resolving the
open question flagged in STATE.md. [VERIFIED: `uv run python` against tree-sitter-language-pack 1.8.1]

**Primary recommendation:** Create a frozen-dataclass `Language` registry whose
`name` equals the tree-sitter-language-pack parser name, seed it from the union
of the existing extension maps (preserving every current extension), expose
`language_for_path()` / `language_by_name()` plus module constants, then migrate
the four named surfaces to delegate. Canonicalize `shell → bash` at the registry
boundary so the existing bash grammar becomes reachable. Keep all public function
signatures returning language *strings* — only the source of those strings
changes. Critically: the word **"shell" is overloaded** in this codebase — it is
also the name of the bash-exec *tool* in the gateway/router/MCP layers. Those
occurrences are unrelated to language identity and MUST NOT be touched.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Canonical language registry (new) | `infra/code_intel` | — | Pure data + lookup, no I/O, no gateway dispatch; consumed by both core capabilities and infra |
| Extension→language detection | `core/capabilities/semantic_file_memory` | `infra/code_intel` (delegate) | File-memory owns smart_read flow; delegates identity to registry |
| Tree-sitter outline config keys | `core/capabilities/semantic_file_memory` | `infra/code_intel` (key source) | Outline node-kind allowlists stay local; keys must equal canonical names |
| Repo-map tag language detection | `infra/tree_sitter` | `infra/code_intel` (delegate) | PageRank tagger is infra; delegates detection to registry |
| SCIP binary registry keys | `infra/code_intel/scip` | `infra/code_intel` (delegate) | SCIP discovery is infra; keys must equal canonical names |

Per project rule: this new capability belongs in `infra/code_intel/`, NOT a
gateway dispatcher. [CITED: additional_context project instructions]

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DLS-LANG-01 | A canonical language registry exists as single source of truth for language identity, extensions, parser names, and SCIP indexer metadata | `Language` dataclass + `LANGUAGES` table design below; field set (`name`, `extensions`, `parser_name`, `scip_indexer`) confirmed against M1 plan and existing surface data |
| DLS-LANG-02 | Extension-based detection delegates to the registry while preserving the `"text"` fallback | `_language_for` (capability.py:81) currently returns `.get(suffix, "text")`; registry `language_for_path()` returns `None`, caller maps `None → "text"`. Consumers at capability.py:318,431 |
| DLS-LANG-03 | Shell extensions (`.sh`, `.bash`, `.zsh`) resolve to canonical tree-sitter bash key | Bug root cause located (capability.py:115-117 → "shell"; grammar keyed "bash" at treesitter_ast.py:291). `get_parser("bash")` verified working. `search_read.py:106-108` already maps these to "bash" — proof the fix is correct |
| DLS-LANG-04 | Tree-sitter config keys, repo-map tag detection, and SCIP registry keys all use canonical names | Four surfaces enumerated below with exact line numbers and current spellings; all canonical names verified to load on tree-sitter-language-pack 1.8.1 |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `tree-sitter-language-pack` | 1.8.1 (installed) | Source of canonical parser names; grammar loading | Already a hard dependency (`pyproject.toml:45`); its parser-name set is the binding constraint for `get_parser()`, so it is the only sensible canonical key authority [VERIFIED: npm/PyPI not needed — already installed, version confirmed via importlib.metadata] |
| `tree-sitter` | >=0.23 (installed) | Underlying parsing runtime | Existing dep (`pyproject.toml:23`) |

**No new packages are introduced in this phase.** This is an internal refactor.
The Package Legitimacy Audit section is therefore N/A (see below).

### Canonical name authority (verified)
The installed `tree-sitter-language-pack` 1.8.1 `SupportedLanguage` Literal
includes all names this milestone needs. Verified to load:

| Need | Canonical name | `get_parser()` | Notes |
|------|----------------|----------------|-------|
| shell/bash | `bash` | ✓ OK | `zsh` also exists as a separate parser, but canonicalize `.zsh → bash` (existing config + search_read.py both use bash) |
| C# | `csharp` | ✓ OK | **NOT `c_sharp`** — resolves STATE.md open question |
| SQL | `sql` | ✓ OK | Used by Phase 17 |
| YAML | `yaml` | ✓ OK | Phase 17 |
| TOML | `toml` | ✓ OK | Phase 17 |
| JSON | `json` | ✓ OK | Phase 17 |

[VERIFIED: `uv run python -c "import tree_sitter_language_pack as p; p.get_parser('bash')..."` — all returned `Parser` objects on 1.8.1]

**Note on built-in detection:** v1.8.1 exposes
`detect_language_from_extension()` / `detect_language_from_path()`. I tested
`detect_language_from_extension('.sh')` → returns `None`. Do **not** rely on the
pack's built-in extension detection; it does not cover the project's extension
set. The registry must own its own extension→language table. [VERIFIED: empirical test returned None]

## Package Legitimacy Audit

**N/A — this phase installs no external packages.** All libraries used
(`tree-sitter-language-pack`, `tree-sitter`) are pre-existing project
dependencies already present in `pyproject.toml` and `uv.lock`. No registry
verification or slopcheck gate applies.

## Architecture Patterns

### System Architecture Diagram

```
                         file path (e.g. "foo.sh")
                                   │
                                   ▼
          ┌────────────────────────────────────────────────┐
          │   infra/code_intel/languages.py  (NEW)          │
          │   ──────────────────────────────────────        │
          │   LANGUAGES: tuple[Language, ...]                │
          │   EXTENSION_TO_LANGUAGE: dict[str, Language]     │
          │   language_for_path(path) -> Language | None     │
          │   language_by_name(name)  -> Language | None     │
          │   Language(name, extensions, parser_name,        │
          │            scip_indexer)                         │
          └───────┬───────────┬───────────┬─────────────────┘
                  │           │           │           │
       delegate   │  key src  │  delegate │  key src  │
                  ▼           ▼           ▼           ▼
     ┌────────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐
     │ capability.py  │ │treesitter│ │ tags.py │ │ scip/        │
     │ _language_for  │ │_ast.py   │ │ detect_ │ │ binaries.py  │
     │ (None→"text",  │ │_LANG_    │ │ language│ │ _SCIP_       │
     │  shell→bash)   │ │CONFIG    │ │         │ │ BINARIES     │
     └───────┬────────┘ │keys ==   │ └────┬────┘ └──────┬───────┘
             │          │canonical │      │             │
             ▼          └────┬─────┘      ▼             ▼
   smart_read outline        ▼      repo-map tags  SCIP indexer
   (returns language    SUPPORTED_                 discovery
    STRING)             LANGUAGES
                        (derived from keys)
```

The registry is a leaf module: pure data + lookup functions, no I/O, importable
by both `core/capabilities/*` and `infra/*` without creating a cycle (it lives in
`infra/code_intel`, which both layers may import).

### Recommended Project Structure
```
src/atelier/infra/code_intel/
├── languages.py          # NEW — canonical Language registry
├── scip/
│   └── binaries.py       # _SCIP_BINARIES re-keyed to canonical names
└── ...
src/atelier/infra/tree_sitter/
└── tags.py               # detect_language delegates to registry
src/atelier/core/capabilities/semantic_file_memory/
├── capability.py         # _language_for delegates; shell→bash
└── treesitter_ast.py     # _LANG_CONFIG keys == canonical; SUPPORTED_LANGUAGES derived
```

### Pattern 1: Frozen dataclass registry with derived lookup tables
**What:** Define an immutable `Language` dataclass, a single `LANGUAGES` tuple,
and derive `EXTENSION_TO_LANGUAGE` / name index at import time.
**When to use:** Single-source-of-truth data tables consumed read-only by many
modules.
**Example:**
```python
# Source: M1-language-registry.md approach + existing surface data
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Language:
    name: str                      # canonical key == tree-sitter-pack parser name
    extensions: frozenset[str]     # incl. leading dot, lowercase
    parser_name: str               # tree-sitter-language-pack key (usually == name)
    scip_indexer: str | None       # e.g. "scip-python"; None if no indexer

LANGUAGES: tuple[Language, ...] = (
    Language("python",     frozenset({".py", ".pyi"}),                 "python",     "scip-python"),
    Language("typescript", frozenset({".ts", ".tsx"}),                 "typescript", "scip-typescript"),
    Language("javascript", frozenset({".js", ".jsx", ".mjs", ".cjs"}), "javascript", "scip-typescript"),
    Language("bash",       frozenset({".sh", ".bash", ".zsh"}),        "bash",       None),
    Language("csharp",     frozenset({".cs"}),                         "csharp",     None),
    # ... go, rust, java, kotlin, scala, ruby, cpp, c, swift, php,
    #     sql, yaml, toml, json, markdown
)

EXTENSION_TO_LANGUAGE: dict[str, Language] = {
    ext: lang for lang in LANGUAGES for ext in lang.extensions
}
_BY_NAME: dict[str, Language] = {lang.name: lang for lang in LANGUAGES}
ALL_LANGUAGES: frozenset[str] = frozenset(_BY_NAME)

def language_for_path(path: str | Path) -> Language | None:
    return EXTENSION_TO_LANGUAGE.get(Path(path).suffix.lower())

def language_by_name(name: str) -> Language | None:
    return _BY_NAME.get(name)
```
[ASSUMED] for the exact `scip_indexer` values beyond the three already present —
M1 only requires the *field to exist*; the full indexer table is populated in
Phase 19 (M4). Seed conservatively: keep the three known indexers
(`scip-python`, `scip-typescript` for ts+js) and set the rest to `None`.

### Pattern 2: Boundary canonicalization (shell → bash)
**What:** Resolve legacy/alias names to canonical at the delegation seam, not by
mutating the registry.
**How:** The registry maps `.sh/.bash/.zsh → Language("bash")` directly, so once
`_language_for` delegates, it naturally returns `"bash"`. No alias map needed if
extension entries point straight at the bash language. Keep the `"text"` fallback
in the caller: `lang = language_for_path(p); return lang.name if lang else "text"`.

### Anti-Patterns to Avoid
- **Adding a new extension/spelling map outside the registry.** STATE.md Watch
  Point: "do not add new extension maps, parser-key maps, or SCIP language maps
  outside the canonical registry." [CITED: STATE.md:98]
- **Touching the `"shell"` *tool* name.** Occurrences in `mcp_server.py`,
  `router.py`, `api.py`, `plugin_runtime.py`, `environment.py`,
  session_parsers, and benchmarks refer to the bash-exec *tool*, not a language.
  Changing them would break tool dispatch. [VERIFIED: grep — 25+ unrelated "shell" tool references]
- **Renaming `_LANG_CONFIG`'s `csharp` key.** It is already canonical
  (`csharp`); no change needed there for C#. Only `shell→bash` is the actual key
  drift in the outline path (and `bash` is already correct in `_LANG_CONFIG`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parser-name validity | A hand-maintained "is this a real grammar" check | `tree_sitter_language_pack.SupportedLanguage` Literal / `get_parser` failure path | The pack already enumerates valid names; existing `_get_parser` already handles unavailable grammars gracefully (treesitter_ast.py:303-313) |
| Extension→language detection | Per-surface dicts (current state) | The new `languages.py` registry | Eliminating the 4–6 duplicated maps IS the phase |

**Key insight:** The duplication itself is the defect. The fix is consolidation,
not new machinery. Resist adding clever auto-detection — the registry is a static
table.

## Runtime State Inventory

This phase changes in-memory language *strings*; it does not change persisted
data formats, service config, OS registrations, secrets, or build artifacts.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `language` strings appear in `smart_read` payloads and the in-memory `_index`, but no on-disk schema keys on the literal `"shell"`. Caches are content-hash keyed, not language-keyed. | None |
| Live service config | None — no external service stores a language name. | None |
| OS-registered state | None. | None |
| Secrets/env vars | SCIP binary env vars (`ATELIER_SCIP_PYTHON_BIN`, `ATELIER_SCIP_TYPESCRIPT_BIN`) are keyed by env-var *name*, not by language string; re-keying `_SCIP_BINARIES` dict keys to canonical names does not change env-var names. | None (verify env-var names unchanged) |
| Build artifacts | None — no compiled output keys on language strings. | None |

**Behavioral migration note (not data migration):** After the fix, shell files
that previously returned `kind: "generic"` outlines will return
`kind: "treesitter"`. Any test or snapshot asserting the old generic behavior for
`.sh` files must be updated. This is a code/test change, not a data migration.
[VERIFIED: capability.py:368-400 outline branch logic]

## Common Pitfalls

### Pitfall 1: Import cycle between core capability and infra registry
**What goes wrong:** Placing the registry where `treesitter_ast.py` and
`capability.py` (core) import infra while infra imports core.
**Why it happens:** `treesitter_ast.py` lives under `core/capabilities`, the
registry under `infra/code_intel`.
**How to avoid:** Registry imports nothing from `core`. Core/infra both import the
leaf registry. Verified safe: registry only needs `pathlib` + stdlib.
**Warning signs:** `ImportError`/circular import at startup; `make typecheck` cycle complaints.

### Pitfall 2: Breaking `SUPPORTED_LANGUAGES` derivation
**What goes wrong:** `SUPPORTED_LANGUAGES` is `frozenset(_LANG_CONFIG.keys())`
(treesitter_ast.py:300) and gates the tree-sitter branch (capability.py:371). If
`_language_for` returns a name not present in `_LANG_CONFIG`, the outline falls
to generic.
**Why it happens:** Mismatch between registry canonical name and `_LANG_CONFIG`
key. Today `bash` is already a `_LANG_CONFIG` key, so `shell→bash` lands
correctly — but any future name drift re-introduces the bug.
**How to avoid:** Add a test asserting every `_LANG_CONFIG` key is a valid
`language_by_name(...)` and (conversely) that registry names intended for
outlining exist in `SUPPORTED_LANGUAGES`.
**Warning signs:** Shell fixture still yields `kind: "generic"`.

### Pitfall 3: `.zsh` / `.bash` extension coverage regression
**What goes wrong:** Dropping an extension when consolidating maps.
**Why it happens:** The 4–6 source maps have *different* extension coverage
(capability.py has the widest; tags.py only 7; post_edit_hooks only 9).
**How to avoid:** Registry extension set must be the **union** of all preserved
extensions. Add a test that every extension in the old `_language_for` map
resolves via the registry to the same (or intentionally canonicalized) name.
[CITED: M1-language-registry.md verify step]
**Warning signs:** A previously-recognized extension returns `"text"`.

### Pitfall 4: Confusing the "shell" tool with the "shell" language
**What goes wrong:** A global find/replace of `"shell"` breaks tool dispatch.
**How to avoid:** Scope edits strictly to the four named code-intel surfaces.
**Warning signs:** MCP tool registration or router tests fail.

## Code Examples

### Migrating `_language_for` (capability.py:80-122)
```python
# Source: existing capability.py + registry delegation
from atelier.infra.code_intel.languages import language_for_path

@staticmethod
def _language_for(path: Path) -> str:
    lang = language_for_path(path)
    return lang.name if lang is not None else "text"
```

### Migrating `tags.py::detect_language` (tags.py:82-91)
```python
# Source: existing tags.py — return type stays `str | None`
from atelier.infra.code_intel.languages import language_for_path

def detect_language(path: Path) -> str | None:
    lang = language_for_path(path)
    return lang.name if lang is not None else None
```
Note: `_regex_tags` only has patterns for js/ts/go/rust; broadening detection
means more languages reach `_regex_tags` and hit the `patterns.get(language,
patterns["javascript"])` default. That is acceptable for M1 (tree-sitter tagging
is M3/Phase 18) but confirm no crash — the default pattern handles it.

### Migrating `scip/binaries.py::_SCIP_BINARIES` (binaries.py:9-13)
```python
# Source: existing binaries.py — keep env-var names + behavior identical
from atelier.infra.code_intel.languages import language_by_name

def discover_scip_binary(language: str) -> Path | None:
    lang = language_by_name(language)
    indexer = lang.scip_indexer if lang else None
    # preserve env-var override mapping; only the language→indexer source moves
    ...
```
Keep `discover_scip_binaries()` iterating the same `("python", "typescript")`
set for M1 (expansion is Phase 19). The env-var names
(`ATELIER_SCIP_PYTHON_BIN`, `ATELIER_SCIP_TYPESCRIPT_BIN`) MUST be preserved.

## Duplicated Language Maps (full inventory)

Confirmed via `grep` of `"\.py":` extension dicts across `src/`:

| # | File / symbol | Coverage today | M1 scope |
|---|---------------|----------------|----------|
| 1 | `semantic_file_memory/capability.py::_language_for` (L81) | ~26 exts; uses `"shell"`, `"csharp"`; fallback `"text"` | **IN — the buggy one; delegate** |
| 2 | `semantic_file_memory/treesitter_ast.py::_LANG_CONFIG` keys (L52) + `SUPPORTED_LANGUAGES` (L300) | 13 keys incl. `bash`, `csharp` | **IN — keys must equal canonical; derive SUPPORTED_LANGUAGES** |
| 3 | `infra/tree_sitter/tags.py::detect_language` (L82) | 7 exts (py/js/ts/go/rs) | **IN — delegate** |
| 4 | `infra/code_intel/scip/binaries.py::_SCIP_BINARIES` (L9) | python/typescript/javascript | **IN — re-key to canonical** |
| 5 | `tool_supervision/search_read.py::_LANG_MAP` (L87) | ~22 exts; **already uses `"bash"` + `"csharp"` correctly** | OUT of M1 named scope — but the correct reference implementation. Recommend planner note it as an optional follow-on consumer; do not silently leave divergent |
| 6 | `tool_supervision/post_edit_hooks.py::_EXT_TO_LANGUAGE` (L19) | 9 exts (formatter selection) | OUT — formatter concern, not code-intel identity |
| 7 | `tool_supervision/capability.py`, `native_search.py` | contain `".py"` maps (purpose: search/format) | OUT — verify not code-intel identity before touching |

**Decision for planner:** M1 (this phase) MUST migrate maps #1–#4 (the four
surfaces named in the requirements). Maps #5–#7 are out of the locked scope but
should be flagged: #5 already proves the canonical `bash`/`csharp` choice is
correct. Migrating #5–#7 is optional and can be deferred to avoid scope creep.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-surface hardcoded language dicts | Single canonical registry | This phase | Eliminates drift class |
| `.sh → "shell"` (dead-ends at generic outline) | `.sh → "bash"` (reaches tree-sitter) | This phase | Shell files get structural outlines |
| C# spelling uncertainty (`csharp` vs `c_sharp`) | Confirmed `csharp` on pack 1.8.1 | Verified this session | Removes a planning unknown |

**Deprecated/outdated:**
- The comment in `capability.py:95-97` referencing
  `docs/plans/active/savings-honest-ab/README.md` for queued per-language
  outlines is stale relative to the new `docs/plans/dedicated-language-support/`
  plan. Update or remove during migration.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `scip_indexer` field can be seeded with `None` for non-py/ts/js languages in M1 (full table is Phase 19) | Standard Stack / Pattern 1 | Low — M1 only requires the field to exist; Phase 19 owns the values |
| A2 | `.zsh` should canonicalize to `bash` (not the separate `zsh` parser) | Canonical name authority | Low — matches existing `_LANG_CONFIG` (`bash` only) and `search_read.py` (`.zsh → bash`); using `zsh` parser would orphan it (no `_LANG_CONFIG` entry) |
| A3 | Maps #5–#7 are out of locked M1 scope | Duplicated Language Maps | Low — requirements name exactly the four surfaces; planner can confirm with user |
| A4 | No persisted cache/data keys on the literal language string `"shell"` | Runtime State Inventory | Medium — if a cache snapshot keyed on language exists, shell entries could mismatch. Mitigation: grep cache code during planning; caches observed are content-hash keyed |

## Open Questions (RESOLVED)

1. **Should Phase 16 also migrate `search_read.py::_LANG_MAP` (#5)?**
   - RESOLVED: Keep Phase 16 to the four required surfaces; `search_read.py`
     is out of scope and remains a fast-follow.
   - What we know: it is a 5th extension map and already uses the *correct*
     canonical spellings (`bash`, `csharp`).
   - What's unclear: whether the user wants strict 4-surface scope or full
     consolidation now.
   - Recommendation: keep M1 to the four required surfaces; note #5 as a
     fast-follow. Do not expand scope without confirmation.

2. **`scip_indexer` initial values** — seed only the three known indexers and
   `None` elsewhere (defer full table to Phase 19), or pre-populate the planned
   Phase-19 indexer names now?
   - RESOLVED: Seed conservatively with only Python, TypeScript, and JavaScript
     SCIP indexers; keep the expanded registry table deferred to Phase 19.
   - Recommendation: seed conservatively (A1). Avoids asserting indexer names
     that Phase 19 will verify against real binaries.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `tree-sitter-language-pack` | Canonical name authority, grammar load | ✓ | 1.8.1 | — |
| `tree-sitter` | Parsing runtime | ✓ | >=0.23 | — |
| `uv` | Run commands/tests | ✓ | — | — |
| SCIP indexer binaries | NOT required by M1 (Phase 19/20) | ✗ | — | M1 only re-keys the registry; discovery degrades to "none" as today |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** SCIP binaries are not needed for this
phase — `discover_scip_binaries()` already returns only what is installed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest`) |
| Config file | `pyproject.toml` (project test config); `make test` wraps with xdist when available |
| Quick run command | `uv run pytest tests/core/test_code_context.py -q` |
| Full suite command | `make test` (or `uv run pytest -q`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DLS-LANG-01 | Registry exposes `Language`, `language_for_path`, `language_by_name`, `EXTENSION_TO_LANGUAGE`, `ALL_LANGUAGES` | unit | `uv run pytest tests/infra/code_intel/test_languages.py -x` | ❌ Wave 0 |
| DLS-LANG-02 | Every old `_language_for` extension resolves to same/canonical name; unknown → `"text"` | unit | `uv run pytest tests/infra/code_intel/test_languages.py -k extensions -x` | ❌ Wave 0 |
| DLS-LANG-03 | `.sh/.bash/.zsh` → `"bash"`; shell fixture yields `kind:"treesitter"` not `"generic"` | unit + regression | `uv run pytest tests/core/test_shell_outline.py -k shell -x` | ❌ Wave 0 |
| DLS-LANG-04 | All `_LANG_CONFIG` keys resolve via registry; `tags.detect_language` + `_SCIP_BINARIES` keyed canonical; env-var names unchanged | unit | `uv run pytest tests/infra/code_intel/test_languages.py -k canonical tests/infra/code_intel/scip/test_scip_adapter.py -x` | ⚠ partial (scip adapter exists) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/infra/code_intel/test_languages.py tests/core/test_code_context.py -q`
- **Per wave merge:** `make lint && make typecheck && uv run pytest tests/core/test_code_context.py tests/infra -q` [CITED: M1-language-registry.md verify step]
- **Phase gate:** `make lint && make typecheck && make test` green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/infra/code_intel/test_languages.py` — registry unit tests (DLS-LANG-01/02/04): every old extension resolves; `.sh/.bash/.zsh → bash`; `csharp` canonical; unknown → `None`; `_LANG_CONFIG` keys ⊆ registry names.
- [ ] `tests/core/test_shell_outline.py` (or add to `test_code_context.py`) — regression: a `.sh` fixture now produces `kind:"treesitter"` (DLS-LANG-03), mirroring `tests/core/test_rust_outline.py` structure.
- [ ] Confirm `tests/infra/code_intel/` has an `__init__.py` for the new test module path.

*(Existing `tests/infra/code_intel/scip/test_scip_adapter.py` covers SCIP
discovery and can be extended for the re-keyed `_SCIP_BINARIES`.)*

## Security Domain

`security_enforcement` is not set to `false` in config — but this phase has a
minimal security surface (internal refactor, no untrusted input, no new
network/auth/crypto). The one relevant control:

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes (low) | Extension lookup uses `Path(path).suffix.lower()`; no path traversal or injection risk — registry is a pure dict lookup. `search_read.py` already enforces shell-metachar rejection separately (unchanged by this phase). |
| V2/V3/V4/V6 | no | No auth, session, access-control, or crypto changes |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Accidentally renaming the `"shell"` *tool* | Tampering (broken dispatch) | Scope edits to the four code-intel surfaces only; do not touch gateway/router/MCP "shell" tool references |

## Sources

### Primary (HIGH confidence)
- Codebase grep + file reads: `capability.py` (L80-122, L310-400), `treesitter_ast.py` (L52-313), `tags.py`, `scip/binaries.py`, `search_read.py` (L87-150), `post_edit_hooks.py` (L19-33) — current map coverage and the shell/bash bug
- `uv run python` against `tree-sitter-language-pack` 1.8.1 — verified canonical names `bash`/`csharp`/`sql`/`yaml`/`toml`/`json`/`zsh` load; `detect_language_from_extension('.sh')` returns `None`; version via `importlib.metadata`
- `docs/plans/dedicated-language-support/M1-language-registry.md` and `index.md` — design intent, `Language` dataclass shape, verify step
- `.planning/REQUIREMENTS.md` (L139-142), `.planning/STATE.md` (decisions + Watch Points), `.planning/config.json` (nyquist_validation: true)

### Secondary (MEDIUM confidence)
- `pyproject.toml` / `uv.lock` — dependency declarations (`tree-sitter-language-pack>=1.8.1`)

### Tertiary (LOW confidence)
- None — all material claims verified against codebase or live interpreter.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; canonical names verified on the
  installed pack version
- Architecture: HIGH — design is dictated by the M1 plan and verified against the
  four real surfaces with exact line numbers
- Pitfalls: HIGH — the shell/bash bug and the "shell tool" overload were both
  located in source

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (stable internal refactor; revalidate if
`tree-sitter-language-pack` is bumped, since parser names could shift)
