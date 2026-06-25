# Atelier Launch — Workstreams Tracker

**Created:** 2026-06-13 · Companion to `.planning/LAUNCH-READINESS.md` (the review + findings doc).
**This file is the execution checklist** — we work it top-to-bottom and tick boxes as we go.

**Legend:** `[ ]` todo · `[~]` in progress · `[x]` done · 🔴 blocker · 🟡 partial · ✅ verified · ❓ unverified

## Status dashboard

| WS | Title | State | Note |
|----|-------|-------|------|
| WS0 | Green baseline | 🟡 near-done | lint/mypy/collection ✅; ≥1 real test failure; suite too slow serially |
| WS1 | Feature completeness audit | 🟡 in progress | 10 of ~19 families triaged |
| WS2 | Testing & benchmarking | 🔴 not started | **savings/SWE benchmark impls deleted** |
| WS3 | Cleanup / removal | 🟡 | register in LAUNCH-READINESS §7; C11 done |
| WS4 | Simplification (god-files) | ⬜ not started | 7 files >1.8k LOC |
| WS5 | Launch infrastructure | 🔴 not started | `make launch-gate` broken |
| WS6 | release-todo items | ⬜ not started | atelierd, install, lessons extraction |

## 🔥 Confirmed defects (actionable now)

- [ ] D1 🔴 Benchmark **implementations deleted** — SWE-bench harness + WP-50 savings-replay gone repo-wide (proves launch goals #1/#2). Rebuild or restore. (LR §2)
- [ ] D2 🔴 Session ingest **silently drops data** — `ingest_session.py:65` TODO; returns `success`, persists no traces. Also `ingest_session_directory.py`.
- [ ] D3 🔴 `make launch-gate` broken — references missing `scripts/launch_gate.sh`.
- [ ] D4 🔴 atelierbench CLI↔runner contract break (runtime, not test-only): `run.py:2152` defines `tasks` as a **positional** arg with no `--tasks` flag, but the production wrapper `atelier benchmark` (`benchmark.py:671-676`) emits `python -m benchmarks.atelierbench.run --tasks <ids> --arms ...`. So the headline `atelier benchmark` command crashes at launch with `unrecognized arguments: --tasks` — the same failure `test_atelierbench.py::test_main_resume_skips_existing_runs` catches. Stale `--tasks` flag also encoded in `test_benchmark_cli_actions.py:94`. **Decision needed:** align on positional (fix wrapper + 2 tests) vs restore `--tasks` flag in runner (fix runner argparse + docstring examples).
- [ ] D5 🟡 Fast suite unusable serially — no-`-x` run timed out >30 min; depends on `-n auto`. Confirm no hang; document the real run command.
- [ ] D6 🟡 **Dangling CHANGELOG evidence links** — 0.3.1 cites `docs/benchmarks/v3-honest-savings.md` + `docs/migrations/v2-to-v3.md` + deprecation matrix; **none exist**. Restore or delete the references (honesty).

---

## WS0 — Green baseline 🔴 (gate for everything)

- [x] WS0.1 `source_projection/minify.py` lint+mypy clean (owner finished WIP)
- [x] WS0.2 Remove 15 `benchmarks.code_intel` orphan tests (impl gone)
- [x] WS0.3 Remove 3 `benchmarks.swe.*` orphan tests (impl gone)
- [x] WS0.4 Remove `tests/core/capabilities/sync/` orphan (capability deleted 5483a5d)
- [x] WS0.5a lint ✅ + mypy ✅ (488) + collection ✅ (0 errors / 2,539 collected)
- [~] WS0.5b `make test-fast` green end-to-end — D4 root-caused as a runtime CLI break (not a stale test); full-green + D5 confirmation still need a parallel run
- [ ] WS0.7 Resolve D4 atelierbench `--tasks` contract break (decision: align positional vs restore `--tasks` flag — see D4)
- [ ] WS0.6 Run `make test` (parallel) once; record true pass/skip/fail baseline; supersede stale `docs-internal/launch-readiness.md` — ⛔ BLOCKED 2026-06-13: `mcp__atelier__shell` returns "dict object expected; got str" on every call after the MCP reconnect; needs a full server restart, not just `/mcp` reconnect

---

## WS1 — Feature completeness audit (CURRENT FOCUS)

For each family: confirm wired · confirm it does what it claims · note test coverage · assign
final ✅/🟡/🔴 · list what testing/benchmarking it needs. Detailed verdicts in LR §3.

### Triaged
- [x] WS1.1 **Owned-CLI `atelier run`** — ✅? substantially built (10-module pkg; start/resume/report) + unit-tested. TODO: e2e smoke (creds) + savings benchmark.
- [x] WS1.5 **Workflow family** — 🟡 wired (owned-exec/service/MCP), has runner test. TODO: verify e2e behavior.
- [x] WS1.8 **Session ingest** — 🔴 data-drop confirmed (D2). Finish persistence or gate off.
- [x] WS1.9 **SDK client** — ❓ likely abstract base (`local/remote/mcp` siblings). TODO: confirm subclasses implement all methods.

### To audit (deeper pass)
- [x] WS1.2 **Code intelligence** — ✅ mature: **67 test files** incl. surviving A/B benchmarks (`test_code_search/explore/routes_ab_real`, `test_read_ab_real`) + quality benches; 12 sane sibling modules. Caveats: `engine.py` 7,819-line god-file (→WS4.1). (Deleted `benchmarks/code_intel/` was a *redundant* set.)
- [ ] WS1.3 **Memory system** (`memory/`, `archival_recall/`, `cross_vendor_memory/`, `memory_arbitration/`, `consolidation/` + letta/openmemory bridges) — exercise each backend
- [x] WS1.4 **Savings / reporting / insights** — 🟡 numbers are **transcript-grounded (real, not synthetic)**; surviving per-tool A/B benchmarks (`test_read/edit/search/shell_ab_real`, `test_swebench_token_savings`, `mark.ab`). Gaps: aggregate replay benchmark deleted (D1) + published evidence docs missing (D6); review `reduction_pct`/baseline methodology.
- [ ] WS1.6 **Routing** (`quality_router/`, `model_routing/`, `cross_vendor_routing/`, `providers/`) — verify decisions
- [x] WS1.7 **Swarm** — 🟡 works (9 test files); confirmed 2× `shell=True` on interpolated `command` (`capability.py:2112,2608` + `cli/swarm.py:381`). Power-user feature; harden before launch (→WS4.5).
- [ ] WS1.10 **Team / auth / governance / audit** — confirm v1 scope or descope
- [x] WS1.11 **Context reuse / Playbooks** — ✅ core value prop, engine-wired, **32 test files** (bm25/ranking/dead_ends). Needs the aggregate savings benchmark to quantify (D1).
- [x] WS1.12 **Tool supervision** — ✅ **backbone of the agent-facing MCP tools** (bash_exec, batch_edit, rich_edit, symbol_edit, smart_search, read_discipline, path_safety, command_discipline, sql_tool...). 23 modules, **27 test files**. Central + well-covered.
- [ ] WS1.13 **Proof / verification / eval** (`proof_gate/`, `verification/`, `eval_mini/`, rubrics) — `env validate` rubric gap
- [ ] WS1.14 **Optimization advisor** (`optimization/` 2.4k) — `atelier optimize`; verify
- [ ] WS1.15 **Source projection** (`source_projection/`) — minify reads now clean; verify read/edit fidelity + tests
- [ ] WS1.16 **Telemetry** (`service/telemetry/`, OTel/PostHog/Langfuse) — verify redaction + opt-out
- [ ] WS1.17 **MCP tool surface** (12 stable) + **HTTP service** (~85 routes) — per-tool/route behavior + dev-mode gating
- [ ] WS1.18 **Integrations / host adapters** (aider, continue, cursor, hermes, langgraph, openhands, sweagent) + Claude plugin/hooks
- [ ] WS1.19 **Storage / embeddings / internal_llm** backends — each provider path
- [ ] WS1.20 Assign every family a final verdict in LR §3

---

## WS2 — Testing & benchmarking 🔴

- [ ] WS2.1 Rebuild/restore deleted savings + SWE benchmarks (D1) — prove launch goals #1/#2
- [ ] WS2.2 Host-adapter tests (7 adapters, ~1 test file today)
- [ ] WS2.3 Service-route coverage (~85 routes)
- [ ] WS2.4 CI installs optional extras so api/postgres/worker tests run (not silent-skip)
- [ ] WS2.5 Un-skip / replace benchmark-solver CLI skip
- [ ] WS2.6 Re-enable mypy strictness incrementally (start `gateway.cli.app`)
- [ ] WS2.7 Establish real coverage floor (`make test-full`, calibrate `COV_FAIL_UNDER`)
- [ ] WS2.8 Make the fast suite usable (parallel default / fix slowness from D5)

---

## WS3 — Cleanup / removal (register: LR §7; nothing deleted until `approved`)

- [x] WS3.0 C11 orphaned tests removed (done 2026-06-13)
- [ ] WS3.1 Local-only junk (build dirs, 9 experimental `.spec`, root `fix_*.py`, `cost_history.json`, `landing/` 231M, `reports/` 26M)
- [ ] WS3.2 Decide fate of deleted `.planning` GSD docs (commit deletion vs restore roadmap)
- [ ] WS3.3 Consolidate doc trees (`docs/` vs `docs-internal/` 243f vs `docs-site/`)
- [ ] WS3.4 Prune one-off scripts (`scripts/fix_silent_exceptions.py`, `mass_replace.py`, `debug_code_matrix.py`)
- [ ] WS3.5 Verify tracked data files still used (`semantic_file_index.json`, `openapi_letta.json` 1.7M)

---

## WS4 — Simplification (god-files; only with tests as safety net)

- [ ] WS4.1 `code_context/engine.py` (7,819) → indexer/parser/retrieval/storage
- [ ] WS4.2 `service/api.py` (6,835) → routers per resource
- [ ] WS4.3 `mcp_server.py` (7,664) → per-tool handler registry
- [ ] WS4.4 `swarm/capability.py` (2,731), `_session_parser.py` (2,306), `store.py` (1,943), `sessions.py` (1,941)
- [ ] WS4.5 `shell=True` → arg-list / `shlex.quote` (swarm + `cli/swarm.py`) — security
- [ ] WS4.6 Narrow the ~256 "Recovered from broad exception handler" sites where the failure mode is known

---

## WS5 — Launch infrastructure 🔴

- [ ] WS5.1 Restore `scripts/launch_gate.sh` / fix `make launch-gate` (D3); define the gate
- [ ] WS5.2 Verify `make release` / `build.sh` produces a working binary
- [ ] WS5.3 One-command install across all host CLIs + `atelier` CLI (release-todo)
- [ ] WS5.4 Verify install/uninstall/status scripts + `atelier doctor`
- [ ] WS5.5 Refresh `docs-internal/launch-readiness.md` from real numbers; align README/QUICK_REFERENCE
- [ ] WS5.6 `make check-agent-context` + docs gates green

---

## WS6 — release-todo.md items

- [ ] WS6.1 `atelierd` background daemon (`infra/runtime/daemon_units.py` exists — finish/wire)
- [ ] WS6.2 One-command install ready on all CLIs (overlaps WS5.3)
- [ ] WS6.3 In-conversation lessons extraction when an instruction fails

---

## Decisions still open (LR §6)

- [ ] Owned-CLI `atelier run` in scope for v1, or tracked-deferred?
- [ ] Keep multi-user team/auth/governance in v1, or descope to single-user?
- [ ] Restore deleted `.planning` roadmap as official feature roadmap, or keep these docs as the only plan?
- [ ] Rebuild deleted savings/SWE benchmarks now (D1) or accept reduced launch-claim scope?
