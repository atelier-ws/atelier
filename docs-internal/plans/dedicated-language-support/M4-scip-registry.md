# M4 — Expand SCIP Indexer Registry

**Goal:** Extend semantic intelligence (callers/callees, go-to-def) beyond
Python/TS/JS to every language with a maintained SCIP indexer: **go, rust,
java, ruby, c/c++**.

## Files to touch

- `src/atelier/infra/code_intel/scip/binaries.py` (`_SCIP_BINARIES`,
  `discover_scip_binaries`).
- `src/atelier/infra/code_intel/scip/indexer.py` (or `adapter.py`) — the code
  path that *runs* an indexer to produce a `.scip` artifact (today the indexer
  only *discovers* pre-built artifacts).
- `tests/` — SCIP discovery/registry tests.

## Indexer matrix

| Language | Binary | Provenance | Invocation note |
|---|---|---|---|
| Python | `scip-python` | npm `@sourcegraph/scip-python` | present today |
| TS/JS | `scip-typescript` | npm `@sourcegraph/scip-typescript` | present today |
| Go | `scip-go` | `go install github.com/sourcegraph/scip-go` | needs Go toolchain |
| Rust | `rust-analyzer scip` | rustup component | subcommand, not standalone |
| Java | `scip-java` | coursier `com.sourcegraph:scip-java` | needs JDK + build tool |
| Ruby | `scip-ruby` | gem `scip-ruby` | |
| C/C++ | `scip-clang` | GitHub binary release | needs `compile_commands.json` |

## Approach

1. Extend `_SCIP_BINARIES` to map each canonical language (M1) to
   `(env_var, fallback_command)`. For `rust-analyzer scip` model the
   subcommand: store `("ATELIER_SCIP_RUST_BIN", "rust-analyzer")` plus a
   per-language argv template (`["scip"]`) so the runner knows how to invoke it.
2. Generalize `discover_scip_binaries()` to iterate the registry instead of the
   hard-coded `("python", "typescript")` tuple.
3. Add an *indexing* path (currently absent) that, given a repo + language +
   discovered binary, runs the indexer to emit a `.scip` into the repo-local
   cache (`default_scip_cache_root`). Keep it opt-in/lazy — indexers are slow
   and some need project build context (Java, C++).
4. Each indexer has distinct flags (output path, project root, toolchain
   version). Encapsulate per-language argv construction behind one function so
   adapters stay thin.

## Verify

- Registry test: every canonical language with an indexer resolves its env-var
  override and fallback name.
- With `scip-go` installed in CI (or mocked), indexing a Go fixture produces a
  readable `.scip` that `scip/reader.py` can parse into symbols.
- `make lint && make typecheck && uv run pytest tests -k scip -q`.

## Notes / risks

- Java and C++ indexers need build context (`compile_commands.json`, a build
  tool). Treat those as best-effort: discover + run only when the context
  exists, else skip cleanly. Document the requirement.
- This milestone only adds the *capability*; provisioning the binaries is M5.
