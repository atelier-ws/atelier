# Dedicated Language Support

> Status: **proposed** · Owner: unassigned · Created: 2026-05-29
>
> This plan is structured as independent milestones so sub-agents / the harness
> can pick up one milestone file at a time. Each milestone file is
> self-contained: goal, files to touch, approach, and a verify step.

## Problem

Atelier recognizes 21+ languages by file extension, but the *quality* of code
intelligence drops off a cliff outside a small core:

- **3 languages** (Python, TypeScript, JavaScript) get native AST outlining.
- **12 languages** get a dedicated tree-sitter structural outline.
- **Everything else** (Shell, YAML, TOML, JSON, SQL, and any unconfigured
  language) falls back to a regex "generic" outline.
- **Repo-map symbol tags** only exist for Python (AST) and JS/TS/Go/Rust
  (regex). The other 9 tree-sitter languages contribute *no* symbols to the
  PageRank repo map.
- **SCIP semantic indexing** (callers/callees, go-to-def) only supports
  Python + TypeScript/JavaScript, and only if the indexer binary already
  happens to be on `PATH`. Atelier never provisions the binaries.

The goal: give **every recognized language** first-class treatment —
dedicated structural outlining, symbol tagging, and (where an indexer exists)
SCIP semantic intelligence — and **ship the SCIP indexers as part of the
Atelier runtime environment** so semantic intel works out of the box.

## Current-state map (ground truth)

| Surface | File | Coverage today |
|---|---|---|
| Extension → language | `src/atelier/core/capabilities/semantic_file_memory/capability.py` (`_detect_language`) | 21+ extensions, fallback `"text"` |
| Native AST outline | same file (python/ts/js builders) | Python, TS, JS |
| Tree-sitter outline | `src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py` (`_LANG_CONFIG`) | go, rust, java, ruby, c, cpp, csharp, kotlin, php, swift, scala, **bash** |
| Generic regex outline | `capability.py` (`_generic_outline_text`) | everything else (incl. shell, yaml, toml, json, sql) |
| Repo-map symbol tags | `src/atelier/infra/tree_sitter/tags.py` | Python (AST); JS/TS/Go/Rust (regex) |
| SCIP binaries registry | `src/atelier/infra/code_intel/scip/binaries.py` | python, typescript, javascript |
| SCIP provisioning | `scripts/install.sh`, `scip/indexer.py` | **none** — discovers only pre-installed binaries |

### Known defects this plan fixes

1. **Shell never reaches tree-sitter.** `_detect_language` returns `"shell"`
   for `.sh/.bash/.zsh`, but `_LANG_CONFIG`'s key is `"bash"`. Since
   `"shell" not in SUPPORTED_LANGUAGES`, shell files silently fall through to
   the generic outline. The dedicated bash grammar is dead code for real files.
2. **No language-name canonicalization.** The extension map, the tree-sitter
   config keys, the tags detector, and the SCIP registry each use their own
   spelling (`shell` vs `bash`, `csharp` vs `cs`, `cpp` vs `c++`). There is no
   single source of truth, so mismatches are easy to introduce.

## Scope

**In scope**
- Dedicated structural outlining for all currently-generic languages that have
  a usable tree-sitter grammar (shell, yaml, toml, json, sql).
- Tree-sitter-based repo-map symbol tags for all tree-sitter languages
  (replacing the regex tagger).
- Expanding the SCIP registry to every language with a maintained indexer
  (go, rust, java, ruby, c/c++; python/ts/js already present).
- Provisioning SCIP indexers inside the Atelier runtime environment (install
  script + on-demand bootstrap) so semantic intel works without manual setup.
- A single canonical language registry that all four surfaces share.

**Out of scope**
- New languages not already recognized by extension (no Lua, Elixir, etc.).
- LSP-based intel (tracked separately in `docs/plans/code-intel/`).
- External-dependency indexing (already tracked in `code-intel/M9`).

## Milestones

| # | File | Outcome | Depends on |
|---|---|---|---|
| M1 | `M1-language-registry.md` | One canonical language registry; fix shell/bash bug; all surfaces read from it | — |
| M2 | `M2-treesitter-coverage.md` | Dedicated tree-sitter outlines for shell, yaml, toml, json, sql | M1 |
| M3 | `M3-treesitter-tags.md` | Repo-map symbol tags via tree-sitter for all tree-sitter languages | M1 |
| M4 | `M4-scip-registry.md` | SCIP registry + indexer execution for go, rust, java, ruby, c/c++ | M1 |
| M5 | `M5-scip-runtime-provisioning.md` | SCIP indexers shipped/bootstrapped in the Atelier runtime env | M4 |
| M6 | `M6-validation-and-docs.md` | Per-language fixtures, savings benchmark, updated docs | M2–M5 |

M1 is the keystone; M2/M3/M4 can run in parallel after M1. M5 depends on M4.
M6 closes out after the others.

## Dependencies

- `tree-sitter-language-pack` (already a dependency — confirm grammars for
  `yaml`, `toml`, `json`, `sql` are bundled; see M2 verify step).
- SCIP indexers: `scip-python`, `scip-typescript` (npm), `scip-go` (go),
  `rust-analyzer scip` (rustup), `scip-java` / `scip-semanticdb` (coursier),
  `scip-ruby` (gem), `scip-clang` (binary release).
- `scripts/install.sh` already installs Node + npm globals into
  `$ATELIER_NODE_DIR`; M5 extends this.

## Validation (whole-plan)

- `make lint && make typecheck && make test` green.
- New per-language fixture tests under
  `tests/core/test_semantic_file_memory*` and
  `tests/infra/test_tree_sitter_tags*`.
- A savings benchmark showing outline token-savings for the newly-dedicated
  languages clears the existing 25% guard more often than the generic path.
- `uv run atelier` (or the relevant CLI/MCP smoke test) reports SCIP binaries
  as available for the expanded language set after install.

## Open questions

1. **Bundle vs. fetch SCIP binaries** — `code-intel/M1` leaned
   fetch-on-first-use with a checksum allowlist. Confirm that decision still
   holds for the expanded set (Go/Rust/Java toolchains are large). See M5.
2. **Data languages (YAML/TOML/JSON)** — outline value is lower than code.
   Decide whether to outline (top-level keys / table headers) or keep them on
   the generic path. M2 proposes outlining top-level structure only.
3. **Canonical names** — adopt tree-sitter-language-pack's spelling as the
   canonical key set, or Linguist's? M1 proposes tree-sitter-pack names since
   that is the hard constraint for parser loading.
