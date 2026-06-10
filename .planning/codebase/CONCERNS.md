# Codebase Concerns

**Analysis Date:** 2026-06-08

## Tech Debt

**Oversized God-files (low maintainability):**
- Issue: Several modules far exceed any reasonable size threshold, mixing many responsibilities in one file. They are hard to navigate, review, and test in isolation.
- Files:
  - `src/atelier/core/capabilities/code_context/engine.py` (7,820 lines) — symbol index + retrieval + AST parsing + sqlite + subprocess + threading all in one module
  - `src/atelier/gateway/adapters/mcp_server.py` (7,257 lines)
  - `src/atelier/core/service/api.py` (6,660 lines) — entire FastAPI surface in one file
  - `src/atelier/core/capabilities/swarm/capability.py` (2,731 lines)
  - `src/atelier/gateway/hosts/session_parsers/_session_parser.py` (2,281 lines)
  - `src/atelier/core/capabilities/plugin_runtime.py` (2,041 lines)
  - `src/atelier/core/foundation/store.py` (1,943 lines)
- Impact: High merge-conflict risk, slow comprehension, difficult unit testing of internal helpers, IDE/type-checker slowdown.
- Fix approach: Split by responsibility — e.g. carve `engine.py` into indexer/parser/retrieval/storage submodules; split `api.py` into FastAPI routers per resource; extract the per-tool handlers in `mcp_server.py` into a registry of small modules.

**Pervasive broad exception handling that swallows errors:**
- Issue: ~256 sites log `"Recovered from broad exception handler"` and continue; 320 `except Exception` sites overall, with ~37 `except ... : pass` blocks. Broad rescue obscures real failures and produces silent degradation.
- Files: widespread; representative `src/atelier/core/service/ingest_session.py:60`, `src/atelier/gateway/cli/commands/__init__.py` (lazy command import swallows `ModuleNotFoundError`/`ImportError`), `src/atelier/gateway/cli/commands/admin.py:654`.
- Impact: Failures masked as "success/recovered"; debugging requires log spelunking; partial state can propagate.
- Fix approach: Narrow exception types where the failure mode is known; for genuine catch-alls, re-raise after logging or surface a typed error result rather than silently continuing.

**Unfinished trace persistence (explicit TODOs):**
- Issue: Reconstructed ledger events are not stored as traces.
- Files: `src/atelier/core/service/ingest_session.py:66`, `src/atelier/core/service/ingest_session_directory.py:68`
- Impact: Ingested sessions return `status: success` but the reconstructed ledger is dropped — data is not persisted to the store.
- Fix approach: Implement the trace-write path into the foundation store before treating ingest as complete.

## Known Bugs

**No specific runtime bugs documented in code or CHANGELOG.**
- The `CHANGELOG.md` has an open `## Unreleased` section but no logged defects.
- Closest signals are the broad-exception "Recovered" log sites (see Tech Debt), which can hide latent bugs rather than represent confirmed ones.
- Recommendation: Treat the silent-recovery sites as the primary place where undetected bugs accumulate.

## Security Considerations

**`shell=True` subprocess execution (command-injection surface):**
- Risk: Commands are passed to the shell as formatted strings; if any interpolated path/ref/command is attacker- or config-influenced, this is an injection vector.
- Files:
  - `src/atelier/core/capabilities/swarm/capability.py:2112`, `:2608`
  - `src/atelier/gateway/cli/commands/swarm.py:380-381` (comment explicitly acknowledges `shell=True` for "formatted strings with paths and multiple refs")
- Current mitigation: `src/atelier/core/foundation/redaction.py` provides defense-in-depth redaction noted as protecting against future `shell=True` changes.
- Recommendations: Prefer `subprocess.run([...], shell=False)` with argument lists; if shell is unavoidable, validate/escape interpolated values with `shlex.quote` and constrain command templates to a vetted allowlist.

**Empty-string secret env injection in benchmark harness:**
- Risk: `agent_env_args.extend(["--agent-env", "ANTHROPIC_API_KEY="])` injects a blank API key into the benchmark agent environment.
- Files: `src/atelier/gateway/cli/commands/benchmark.py:768`
- Current mitigation: Limited to benchmark tooling, not production runtime.
- Recommendations: Confirm this is intentional credential-scrubbing (not accidental); document the intent inline.

**Secrets handling (informational):**
- `.env.production.example` present (template only). No hardcoded credentials found in `src/` (only env-var-driven lookups). Continue to keep secrets out of source.

## Performance Bottlenecks

**Synchronous subprocess + file I/O in capability hot paths:**
- Problem: Swarm validation runs external commands sequentially via blocking `subprocess.run` while streaming to log files.
- Files: `src/atelier/core/capabilities/swarm/capability.py:2104-2117`, `:2604-2616`
- Cause: Blocking, serial execution of integration validations.
- Improvement path: Parallelize independent validations (thread/process pool) and bound concurrency; collect results asynchronously.

**Monolithic indexing engine:**
- Problem: `code_context/engine.py` combines sqlite access, AST parsing, multiprocessing, and threading in a single module.
- Files: `src/atelier/core/capabilities/code_context/engine.py`
- Cause: Tight coupling makes targeted profiling/caching hard.
- Improvement path: Isolate the storage layer so query and index phases can be benchmarked and cached independently.

## Fragile Areas

**Session parsers (host-format coupling):**
- Files: `src/atelier/gateway/hosts/session_parsers/_session_parser.py` (2,281), `copilot.py` (1,420), `codex.py` (868), `_common.py` (896)
- Why fragile: Parse loosely-typed external session payloads (`dict[str, Any]`) with many conditional branches and normalization helpers (`_normalize_todos`, `_extract_todos`). Upstream host format changes silently break extraction.
- Safe modification: Add fixture-based regression tests for each host format before editing; change one parser at a time.
- Test coverage: Parser tests exist under `tests/gateway/` but rely on captured fixtures; new host versions are uncovered until a fixture is added.

**FastAPI service surface in one module:**
- Files: `src/atelier/core/service/api.py`
- Why fragile: All routes/handlers co-located; the module is explicitly excluded from some mypy strictness (`untyped-decorator` disabled).
- Safe modification: Split into routers; add request/response models before refactoring.

## Scaling Limits

**SQLite-backed local index:**
- Current capacity: `engine.py` uses `sqlite3` for the symbol index (single-writer, file-locked).
- Limit: Concurrent writers and very large repos stress single-file SQLite; threading/multiprocessing in the same module increases lock contention risk.
- Scaling path: A Postgres backend exists (`src/atelier/infra/storage/postgres_store.py`, 1,292 lines) — route heavy/shared workloads there; keep SQLite for single-user local mode.

## Dependencies at Risk

**Heavy/wide optional-dependency matrix:**
- Risk: Many optional extras (`mcp`, `memory`, `memory-server`, `smart`, `cloud`, `litellm`, `repo-map`, `api`, `postgres`, `vector`, `parsers`, `rename`, `telemetry`) plus pinned native libs (`pygit2==1.19.2`).
- Impact: Optional imports are swallowed via broad `except (ModuleNotFoundError, ImportError)` in `src/atelier/gateway/cli/commands/__init__.py`, so a missing/incompatible extra degrades silently to a missing CLI command rather than a clear error.
- Migration plan: Surface a one-line "command unavailable: install extra X" message instead of silent skip; pin and CI-test each extra combination.

**`pygit2` hard pin:**
- Risk: `pygit2==1.19.2` is exactly pinned and depends on a matching libgit2 ABI.
- Impact: Environment/wheel mismatches break git operations at import time.
- Migration plan: Track libgit2 compatibility; widen to a tested range when feasible.

## Missing Critical Features

**Trace persistence for ingested sessions:**
- Problem: Ledger reconstruction completes but is not written to the store (see TODOs above).
- Blocks: Historical analysis/replay of ingested sessions.

## Test Coverage Gaps

**Benchmark solver CLI untested:**
- What's not tested: `@pytest.mark.skip(reason="benchmark solver CLI needs a deterministic offline harness")`
- Files: `tests/gateway/test_cli_core_capabilities.py:19`
- Risk: CLI regressions in the benchmark solver path go undetected.
- Priority: Medium

**API/integration tests skipped without optional extras:**
- What's not tested: Many FastAPI and live-service tests are gated behind `pytest.importorskip("fastapi"/"uvicorn", ...)` — they silently skip when the `api` extra is absent.
- Files: `tests/gateway/test_telemetry_api.py:8`, `tests/gateway/test_optimizations_api.py:9`, `tests/gateway/test_savings_api.py:9`, `tests/gateway/test_mcp_remote_mode.py:95-96`, `tests/gateway/test_generated_agent_contexts.py:110-111`
- Risk: CI without the extras installed gives false-green; ~47 skip/xfail sites total.
- Priority: Medium — ensure CI installs the relevant extras so these run.

**Type-checking blind spots:**
- What's not tested (statically): `pyproject.toml` sets `ignore_errors = true` for `atelier.gateway.cli.app`; disables `untyped-decorator` for `api.py` and `http_api.py`; relaxes strictness for `gateway.cli.commands.*`, `tests.*`, `scripts.*`, `benchmarks.*`.
- Files: `pyproject.toml` (`[[tool.mypy.overrides]]` blocks), plus 68 inline `# type: ignore`/`# noqa` and ~315 `: Any` annotations across `src/`.
- Risk: Type regressions in the CLI app and API decorators are not caught by `mypy --strict`.
- Priority: Medium — re-enable strict checking incrementally, starting with `gateway.cli.app`.

---

*Concerns audit: 2026-06-08*
