# Atelier — Launch-Readiness Review & Work Plan

**Created:** 2026-06-13 · **Owner:** Pankaj · **Version under review:** 0.3.5 · **Status:** NOT launched

This is the single source of truth for getting Atelier launch-ready. It is an end-to-end
review of the **entire current project** — every feature's implementation status, what is
solid vs partial vs broken, and what testing / benchmarking / cleanup / simplification each
needs. We work it **one item at a time**; check items off as we go.

> **Cleanup rule (per owner):** Plan first, delete nothing yet. Every removal candidate is
> tracked in the [Cleanup Register](#7-cleanup-register-tracked--nothing-deleted-yet). We mark
> an item `approved` before it is touched.

## Status legend

| Mark | Meaning |
|------|---------|
| ✅ | Solid — implemented, wired, has tests, no known launch blocker |
| 🟡 | Partial — works but incomplete, thin tests, or unverified depth |
| 🔴 | Broken / stub / known-unfinished — blocks launch in current form |
| ❓ | Needs verification — exists at scale but not yet deep-reviewed this pass |
| ⬜ / ☑️ | Task not done / done |

---

## 1. Executive summary

Atelier is an **agent reasoning runtime** delivered through five surfaces — CLI (`atelier`/`atl`),
stdio MCP server, FastAPI HTTP service, in-process SDK, and a React dashboard — distributed as a
binary bundle. Architecture is a clean three-layer `gateway → core → infra` (see
`.planning/codebase/ARCHITECTURE.md`). It is large: **488 source files**, **43 capability
packages + ~26 capability modules**, **~2,575 collected tests**, ~35 CLI command groups,
~85 service routes.

**Overall verdict:** architecturally sound and broad, but **not launch-ready today**. The
headline blockers:

1. **Test suite is red at collection** — 19 collection errors (orphaned tests pointing at
   removed modules). `make test-fast` aborts before running anything.
2. **Uncommitted WIP is broken** — `source_projection/minify.py` fails lint (1) and mypy (2).
3. **`make launch-gate` is broken** — references `scripts/launch_gate.sh`, which does not exist.
4. **Feature depth is unverified** — several large feature families (owned-CLI, workflow,
   swarm, memory, code-intel) are built at scale but their completeness and quality are
   unconfirmed and thinly tested.
5. **`docs-internal/launch-readiness.md` is stale** — it claims "1,689 passed, 0 failed"; that
   is no longer true. Treat *this* document as authoritative.

The good news: the committed codebase is otherwise clean (lint + mypy-strict pass on all 488
files once the one WIP file is fixed), the CLI loads cleanly, and the architecture supports the
features without rework.

---

## 2. Current health snapshot (verified 2026-06-13 on branch `bench`)

| Gate | Result | Detail |
|------|--------|--------|
| `ruff` lint | ✅ clean (was 🔴) | minify.py WIP finished by owner 2026-06-13; all paths pass |
| `mypy --strict` | ✅ clean (was 🔴) | 488 source files, 0 issues |
| Full collection | ✅ 0 errors (was 🔴 19) | 2,539 tests collect after orphan removal 2026-06-13 |
| `make test-fast` | 🟡 collects, ≥1 real failure (root-caused → D4 🔴) | `test_atelierbench.py::test_main_resume_skips_existing_runs` fails because `atelier benchmark` (`benchmark.py:671`) emits `--tasks`, but `run.py:2152` made `tasks` **positional** — so the headline `atelier benchmark` command is broken at runtime, not just the test. A serial no-`-x` run **timed out >30 min** — suite needs `-n auto`; parallel `make test` count still pending (blocked: `shell` tool down 2026-06-13) |
| `atelier --help` | ✅ loads | EXIT 0, all command groups register |
| Build / bundle | ❓ unverified | `make release` / `build.sh` not run this pass |
| Frontend build+test | ❓ unverified | scripts present; last audit claimed 34/34 green |
| `make launch-gate` | 🔴 broken | missing `scripts/launch_gate.sh` |

### The 19 collection errors (root causes)

| Count | Failing tests | Root cause | Fix direction |
|-------|---------------|-----------|---------------|
| 15 | `tests/benchmarks/code_intel/test_*.py` | `No module named 'benchmarks.code_intel'` (dir doesn't exist; benchmarks pkg ships only `terminalbench`, `ab`) | Restore/rename the module **or** remove orphaned tests |
| 3 | `tests/gateway/test_swe_benchmark_harness.py`, `tests/infra/test_context_savings_smoke.py`, `tests/infra/test_savings_replay.py` | `No module named 'benchmarks.swe.config'` (there is `swe/configs/` dir, not `config.py`) | Fix import path or restore `benchmarks/swe/config.py` |
| 1 | `tests/core/capabilities/sync/test_serializer_syncs_typed_lessons.py` | `core/capabilities/sync/serializer.py` missing (no `sync/` capability exists) | Remove orphaned test or restore capability |

**Resolved 2026-06-13:** all 19 orphaned test files removed (owner-approved). `sync/` was a
deliberate deletion (commit 5483a5d). But verification revealed a bigger issue — see below.

> **⚠️ Major finding — benchmark *implementations* are gone, not just tests.** `src/benchmarks/`
> does not exist; `blame_bench.py`, `BenchConfig`, `benchmarks.swe.config`, `savings_bench`, and
> `savings_replay` exist **nowhere** in the repo. The SWE-bench harness and the **WP-50
> "real measured savings" replay benchmark** (cited in CHANGELOG, the gate that proves launch
> goals #1 token-usage and #2 tool-turns) have been gutted — only the dead test shells remained.
> Removing the tests greened collection but leaves **zero benchmark coverage for the core value
> claims.** This is the headline WS2.4 gap. Surviving suites: `atelierbench`, `mcp_tools`,
> `wire_savings`, `terminalbench`, `mini`.

---

## 3. Feature inventory & status matrix

Status is this-pass triage from size, wiring, stub-signals, and test presence — **not** a deep
per-line audit (that is workstream WS1). Anything marked ❓/🟡 needs confirmation before launch.

### 3.1 Surfaces / entry points

| Feature | LOC | Status | Notes / what's needed |
|---------|-----|--------|----------------------|
| CLI (`gateway/cli`) | — | ✅/❓ | Loads clean, ~35 groups. Per-command depth (esp. `run`, `swarm`, `stack`, `optimize`) unverified |
| MCP server (`adapters/mcp_server.py`) | 7,664 | 🟡 | Shipped + consolidated (0.3.1 → 12 stable tools). God-file; read/edit/minify WIP in flight |
| HTTP service (`service/api.py`) | 6,835 | 🟡 | ~85 routes in one module. God-file; route-level test coverage unverified; mypy decorator-strictness relaxed |
| In-process SDK (`sdk/middleware.py`, `gateway/sdk/client.py`) | — | ❓ | **WS1.9:** `client.py` has 12+ `raise NotImplementedError` — looks like an **abstract base** (siblings `local.py`/`remote.py`/`mcp.py` implement). Confirm subclasses cover all abstract methods (by-design vs unfinished) |
| Frontend dashboard (`frontend/`) | — | ❓ | Build/test/typecheck scripts present; re-verify; bundle code-split is a known post-launch item |

### 3.2 Core capability families

| Family | Key packages (LOC) | Status | What's needed |
|--------|--------------------|--------|---------------|
| **Code intelligence** | `code_context/` (10,121, 13 modules), infra `code_intel` astgrep/zoekt | ✅/🟡 | **WS1.2 done:** mature + **67 test files** incl. surviving A/B benchmarks. 12 sane sibling modules; god-file is isolated to `engine.py` (7,819 → WS4.1). Deleted `benchmarks/code_intel/` was a redundant set, not the live coverage |
| **Context reuse / Playbooks** | `context_reuse/` (1,539) | ✅ | **WS1.11:** core value prop, engine-wired, 32 test files. Needs aggregate savings benchmark to quantify (D1) |
| **Tool supervision** | `tool_supervision/` (6,764, 23f) | ✅ | **WS1.12:** backbone of agent-facing MCP tools (bash/edit/search/read/sql + path_safety/command_discipline). 27 test files. Central + well-covered |
| **Owned-agent CLI (`atelier run`)** | `owned_agent_session/` (10 modules), `owned_execution_*`, `run.py` (463) | 🟡→✅? | **WS1.1 done:** far more complete than stale STATE.md claimed. `run start`/`resume`/`report` all wired; 10-module package (phase_runner, stem_prompt, task_primer, receipt, keepalive, checkpoint, minified_reads, gemini_cache) maps ~1:1 to SESS/CACHE/READ/RPT reqs; **has real unit tests** (owned_agent_session, owned_execution_lanes/routing, stem_prompt, task_primer, checkpoint). Remaining: end-to-end smoke (needs creds) + a savings benchmark (the relevant benchmark was deleted — see §2) |
| **Source projection (minified reads)** | `source_projection/` (1,614) | 🔴 | `minify.py` WIP broken (lint+mypy). Finish or revert |
| **Swarm** | `swarm/` (3,100), `cli/swarm.py` | 🟡 | **WS1.7:** works (9 tests); confirmed 2× `shell=True` on interpolated `command` (`capability.py:2112,2608`, `cli/swarm.py:381`). Power-user feature; harden (→WS4.5) |
| **Memory system** | `memory/`, `archival_recall/`, `cross_vendor_memory/`, `memory_arbitration/`, `consolidation/` + bridges (letta, openmemory) | ❓ | Multi-backend; several have thin/no name-matched tests. Needs integration tests across backends |
| **Routing** | `quality_router/` (1,142), `model_routing/`, `cross_vendor_routing/`, `providers/` | ❓ | Verify routing decisions + add tests (thin coverage signal) |
| **Proof / verification / eval** | `proof_gate/`, `verification/`, `eval_mini/`, rubrics | 🟡 | `make proof-cost-quality` exists. `env validate` no longer ships bundled rubrics (known gap) |
| **Optimization advisor** | `optimization/` (2,383), `session_optimizer.py` | ❓ | `atelier optimize`. Verify + test |
| **Savings / reporting / insights** | `savings_summary.py` (1,027), `reporting/`, `analytics/`, insights | 🟡 | **WS1.4 done:** transcript-grounded (real, not synthetic); surviving per-tool A/B benches (`mark.ab`). Gaps: aggregate replay benchmark deleted (§2/D1) + CHANGELOG evidence docs missing (D6); review baseline/`reduction_pct` methodology |
| **Workflow** | `workflow_*` (~1,300 across 6 modules) | 🟡 | **WS1.5:** NOT dead — wired into `owned_execution_lanes/cache_affinity`, `benchmark_solver`, `service/api.py`, `mcp_server.py`; has `test_mcp_workflow_runner.py`. Verify end-to-end behavior |
| **Benchmark harness** | `benchmark_solver.py` (1,012), `benchmark_gate/evidence/manifest`, `benchmarks/` workspace | 🔴 | **SWE-bench + WP-50 savings-replay implementations DELETED** (see §2), not just tests. `atelierbench` harness has arg drift (failing test). Benchmark-solver CLI skipped. **This is how we prove the 3 launch goals — must be rebuilt/repaired** |
| **Session ingest** | `service/ingest_session*.py` | 🔴 | **WS1.8 CONFIRMED:** `ingest_session.py:65` is literally `# TODO: Store reconstructed ledger events as traces.` then `return {"status":"success"}`. Reports success, persists nothing. Finish or gate off |
| **Team / auth / governance / audit** | `team/`, `auth/`, `governance/`, `audit_export/` | ❓ | Multi-user governance; thin tests. Verify or descope for v1 |
| **Telemetry** | `service/telemetry/`, OTel/PostHog/Langfuse | ❓ | Local-first + opt-out claimed. Verify redaction + export paths |

### 3.3 Integrations & infra

| Area | Status | What's needed |
|------|--------|---------------|
| Host adapters (aider, continue, cursor, hermes, langgraph, openhands, sweagent) | 🟡 | `tests/integrations/` has **~1 test file** — adapters are nearly untested |
| Host instruction generation (`integrations/` + `make sync-agent-context`) | ✅/❓ | Docs-governance tests exist; verify `make check-agent-context` green |
| Claude plugin + hooks (10 scripts) | ❓ | Last audit said compile-clean; re-verify + smoke test |
| Storage (sqlite default / postgres / vector) | 🟡 | Postgres + worker tests gated out of fast suite (need extras in CI) |
| Embeddings (local/ollama/openai/letta/null) | ❓ | Factory present; verify each provider path |
| internal_llm (litellm/ollama/openai) | ❓ | Verify clients + error/result types |

---

## 4. Workstreams (sequenced)

> **Execution tracker:** the live, tickable checklist lives in `.planning/WORKSTREAMS.md`.
> This section is the rationale/overview; tick boxes there as we work.

Recommended order. **WS0 is a hard prerequisite** — we can't trust anything else until the
baseline is green.

### WS0 — Restore a green baseline 🔴 (do first)

- [x] WS0.1 `source_projection/minify.py` — finished by owner; lint + mypy clean (verified 2026-06-13)
- [x] WS0.2 Removed 15 `benchmarks.code_intel` orphaned tests (impl gone repo-wide — confirmed)
- [x] WS0.3 Removed 3 `benchmarks.swe.*` orphaned tests (impl gone — see §2 benchmark-deletion finding)
- [x] WS0.4 Removed `tests/core/capabilities/sync/` orphan (`sync/` deliberately deleted, commit 5483a5d)
- [x] WS0.5a lint ✅ + mypy ✅ (488 files) + collection ✅ (0 errors, 2,539 collected)
- [~] WS0.5b `make test-fast` actually green — D4 root-caused (runtime CLI break, see health row); full count still pending (⛔ `shell` tool returns "dict object expected; got str" after reconnect — needs MCP server restart)
- [ ] WS0.7 Resolve D4: `run.py:2152` `tasks` is positional, but `benchmark.py:671` + `test_benchmark_cli_actions.py:94` + `test_atelierbench.py` all use `--tasks`. **Decision:** align on positional (fix wrapper + 2 tests) vs restore `--tasks` flag in runner (fix argparse + docstring examples). Runtime-affecting — blocks `atelier benchmark`
- [ ] WS0.6 Run full `make test` once; capture baseline pass/skip numbers (supersede stale launch-readiness.md) — ⛔ BLOCKED 2026-06-13: `mcp__atelier__shell` non-functional after reconnect; needs a full MCP server restart

### WS1 — Feature completeness audit (the core ask)

For each 🟡/❓ family in §3, deep-verify: is it complete, partial, or dead? Wired? Does it do
what it claims? Produce a per-feature verdict.

- [ ] WS1.1 Owned-CLI `atelier run` — end-to-end smoke (start/resume), confirm cache receipts (RPT-*), keepalive, dry-run/yolo. **(highest value, partial)**
- [ ] WS1.2 Code intelligence — confirm zoekt/astgrep paths, benchmark precision
- [ ] WS1.3 Memory system — exercise sqlite/letta/openmemory backends; arbitration + consolidation + archival recall
- [ ] WS1.4 Savings / reporting / insights — confirm numbers are honest and reproducible (no unmeasured claims)
- [ ] WS1.5 Workflow family — is it shipped or dead scaffold? Wire or remove
- [ ] WS1.6 Routing (quality/model/cross-vendor/providers) — verify decisions
- [ ] WS1.7 Swarm — verify + security (see WS4 `shell=True`)
- [ ] WS1.8 Session ingest — finish trace persistence or gate the feature off (🔴 drops data today)
- [ ] WS1.9 SDK client — resolve the 22 TODO/stub sites or document as intentional
- [ ] WS1.10 Team/auth/governance/audit — confirm scope for v1 or descope
- [ ] WS1.11 Mark every feature in §3 with a final ✅/🟡/🔴 verdict

### WS2 — Testing & benchmarking gaps

- [ ] WS2.1 Host adapters — add fixture-based tests (currently ~1 test file for 7 adapters)
- [ ] WS2.2 Service routes — coverage for the ~85 routes (currently in one god-file)
- [ ] WS2.3 Ensure CI installs optional extras so api/postgres/worker tests actually run (not silent-skip)
- [ ] WS2.4 Repair + run the benchmark suites that prove the 3 launch goals (token usage, tool turns, quality)
- [ ] WS2.5 Un-skip or replace the benchmark-solver CLI skip (needs offline harness)
- [ ] WS2.6 Re-enable mypy strictness incrementally (start `gateway.cli.app` `ignore_errors=true`)
- [ ] WS2.7 Establish the real coverage floor (`make test-full`, calibrate `COV_FAIL_UNDER`)

### WS3 — Cleanup / removal (see register §7 — nothing deleted until `approved`)

- [ ] WS3.1 Approve + remove local-only gitignored junk (build dirs, experimental specs, root `fix_*.py`, big local dirs)
- [ ] WS3.2 Decide fate of deleted `.planning` GSD docs (`PROJECT/REQUIREMENTS/ROADMAP/STATE/config`) — restore as roadmap, or confirm delete
- [ ] WS3.3 Consolidate doc trees (`docs/` vs `docs-internal/` 243 files vs `docs-site/`)
- [ ] WS3.4 Prune one-off scripts (`scripts/fix_silent_exceptions.py`, `mass_replace.py`, `debug_code_matrix.py`)
- [ ] WS3.5 Verify tracked data files still used: `semantic_file_index.json` (referenced), `openapi_letta.json` (1.7MB)
- [ ] WS3.6 Remove orphaned tests (if WS0 decides modules stay gone)

### WS4 — Simplification (god-files)

High-risk pre-launch; do only after WS0 green and with tests as a safety net. Prioritize the
ones that block testability.

- [ ] WS4.1 `code_context/engine.py` (7,819) → split indexer/parser/retrieval/storage
- [ ] WS4.2 `service/api.py` (6,835) → routers per resource
- [ ] WS4.3 `mcp_server.py` (7,664) → per-tool handler registry
- [ ] WS4.4 `swarm/capability.py` (2,731), `_session_parser.py` (2,306), `store.py` (1,943), `sessions.py` (1,941)
- [ ] WS4.5 `shell=True` → arg-list/`shlex.quote` in swarm + `cli/swarm.py` (security)
- [ ] WS4.6 Narrow the ~256 "Recovered from broad exception handler" sites where failure mode is known

### WS5 — Launch infrastructure

- [ ] WS5.1 Restore `scripts/launch_gate.sh` (or fix the `make launch-gate` target) — define the gate
- [ ] WS5.2 Verify production build: `make release` / `build.sh` produces a working binary
- [ ] WS5.3 One-command install across all host CLIs + the `atelier` CLI (release-todo)
- [ ] WS5.4 Verify install/uninstall/status scripts and `atelier doctor`
- [ ] WS5.5 Refresh `docs-internal/launch-readiness.md` from real numbers; align README/QUICK_REFERENCE
- [ ] WS5.6 `make check-agent-context` + docs gates green

### WS6 — release-todo.md items

- [ ] WS6.1 `atelierd` background daemon (`infra/runtime/daemon_units.py` exists — finish/wire)
- [ ] WS6.2 One-command install ready on all CLIs (overlaps WS5.3)
- [ ] WS6.3 In-conversation lessons extraction when an instruction fails (lessons family exists)

---

## 5. Launch goals (from `docs-internal/launch-readiness.md`)

1. **Low token usage** — measured & optimized (prove via WS2.4 benchmarks)
2. **Few tool turns** — measured & optimized (prove via WS2.4 benchmarks)
3. **No quality compromise** — gated; anything unverified hidden behind `ATELIER_DEV_MODE`

---

## 6. Open questions / decisions needed

- [ ] Is the `atelier run` owned-CLI **in scope for v1 launch** or a tracked-but-deferred feature?
- [ ] Are the missing `benchmarks.code_intel` / `benchmarks.swe.config` modules **deleted on purpose** (→ remove tests) or lost (→ restore)?
- [ ] Keep multi-user **team/auth/governance** in v1, or descope to single-user?
- [ ] Restore the deleted `.planning` roadmap as the official feature roadmap, or keep this doc as the only plan?

---

## 7. Cleanup register (tracked — nothing deleted yet)

Disposition: `pending` → `approved` → `done`. **Local-only** = gitignored, not in the repo
(safe, but irreversible on disk). **Tracked** = committed; removal changes the repo.

| # | Path / pattern | Kind | Size | Disposition | Notes |
|---|----------------|------|------|-------------|-------|
| C1 | `atelier-{mcp,opt2,opt3,opt4,opt5,optimized,mcp-opt4,mcp-opt5}.spec`, `atelier_test.spec` | Local | ~8 KB | pending | 9 experimental PyInstaller specs; keep only `atelier.spec` (13 KB, current) |
| C2 | `fix_duplicates.py`, `fix_importers.py`, `fix_importers_fast.py`, `fix_logger.py` (root) | Local | ~5 KB | pending | One-off migration scripts left at root (gitignored by `/*.py`) |
| C3 | `build/`, `build_dist/`, `bundle/`, `dist/`, `.venv-build/`, `.vite/` | Local | large | pending | Build/venv output; reproducible via `make` |
| C4 | `landing/` | Local | **231 MB** | pending | Gitignored; confirm not needed before deleting |
| C5 | `reports/` | Local | **26 MB** | pending | Gitignored run reports |
| C6 | `cost_history.json` | Local | 144 KB | pending | Gitignored generated artifact |
| C7 | `.eval/`, plus stray AI-tool dirs not in use | Local | — | pending | Confirm none are active configs |
| C8 | `scripts/fix_silent_exceptions.py`, `scripts/mass_replace.py`, `scripts/debug_code_matrix.py` | Tracked | — | pending | One-off dev scripts; confirm unused then remove |
| C9 | Deleted `.planning/{PROJECT,REQUIREMENTS,ROADMAP,STATE,config}.md`, `phase-14-openai-gateway/PLAN.md` | Tracked (deleted in WT) | — | pending | Decide: commit deletion or restore as roadmap (see §6) |
| C10 | `docs-internal/` (243 files) ↔ `docs/` ↔ `docs-site/` overlap | Tracked | 2.1 MB | pending | Consolidate; `docs-internal/launch-readiness.md` is stale, `release-todo.md` to be folded into this plan |
| C11 | Orphaned tests: `tests/benchmarks/code_intel/` (15), `tests/core/capabilities/sync/` (1), 3× `swe.*` importers | Tracked | — | **done** | Removed 2026-06-13 (owner-approved; impls confirmed gone repo-wide). NB: the benchmark *impls* are also gone — see §2 |
| C12 | `semantic_file_index.json` (root, tracked), `openapi_letta.json` (1.7 MB, tracked) | Tracked | 1.8 MB | pending | Verify still used before any action (`semantic_file_index.json` is referenced by indexer) |

---

## 8. Progress log

| Date | Item | Result |
|------|------|--------|
| 2026-06-13 | Initial full-project review + this plan | Done — health verified, inventory built, 19 collection errors + 3 broken gates identified |
| 2026-06-13 | WS0 baseline | Removed 19 orphaned tests → collection clean (2,539). lint+mypy green. Owner finished minify.py. Found: benchmark impls (SWE/WP-50) deleted; atelierbench arg-drift failure remains |
| 2026-06-13 | WS1.1 owned-CLI audit | 🟡→✅? substantially built (10-module pkg, start/resume/report) + unit-tested; needs e2e smoke + savings benchmark |
| 2026-06-13 | WS1.5/1.8/1.9 verdicts | Workflow 🟡 wired (not dead); Session-ingest 🔴 data-drop confirmed; SDK client.py likely abstract base (verify) |
