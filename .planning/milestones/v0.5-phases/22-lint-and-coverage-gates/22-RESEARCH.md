# Phase 22: Lint and Coverage Gates - Research

**Researched:** 2026-05-29
**Domain:** Python tooling — Ruff lint configuration, pytest/coverage gating, GitHub Actions CI
**Confidence:** HIGH (all findings verified by running the repo's own tools this session)

## Summary

Phase 22 installs *prevention gates* before the M2/M3 burn-down work: enable Ruff
`BLE001` (blind-except) and `T20` (flake8-print) so **new** debt fails `make lint`, while
**existing** debt is parked in `per-file-ignores` (not blanket-disabled), and add a nightly
GitHub Actions workflow that runs the full test suite (including `slow` tests) with a
measured `--cov-fail-under` floor. No runtime code changes — this phase touches only
`pyproject.toml`, `Makefile`, and `.github/workflows/`.

The single most important finding: **the milestone baseline numbers (28 blind-excepts, 132
prints) do NOT match what the lint rules actually flag.** `BLE001` flags **295 violations
across 96 files** (it catches every `except Exception` that does not re-raise, not just the
28 `except Exception: pass` sites the grep counted). `T201` flags **97 violations across 19
files** (the grep's 132 `print(` matches include `.print()` method calls, strings, and
comments that the rule correctly ignores). The per-file-ignores worklist must therefore be
generated from `ruff check`, not from the milestone's grep baselines. Both full file lists
are captured below so the planner can hard-code them.

The coverage floor **must be measured during execution, not guessed** (the milestone doc is
explicit). The fast PR path stays untouched (`-m "not slow"`); the new floor applies only to
the nightly full-suite run. There are 2088 collectable tests (87 marked `slow`, 2001
not-slow).

**Primary recommendation:** Add `"BLE"` and `"T20"` to `[tool.ruff.lint] select`, add a
`[tool.ruff.lint.per-file-ignores]` table listing the 96 BLE001 files and 19 T201 files
(verbatim from this doc), add a `test-full` Makefile target (slow-inclusive + coverage), and
add `nightly-coverage.yml` modeled on the existing `tests.yml` test job — with the
`--cov-fail-under` value filled in from a measured full-suite run as an execution step.

## User Constraints

> No CONTEXT.md exists for this phase yet. Constraints below are derived from the milestone
> source docs (the user-designated source of truth) and STATE.md decisions.

### Locked Decisions (from STATE.md + milestone docs)
- **Gates before burn-down**: "Enable BLE001/T20 with per-file ignores first so new debt
  fails while existing debt is fixed phase-by-phase." (STATE.md Key Decisions Log)
- **Per-file-ignores, NOT blanket disables** — the point is to stop *new* violations
  (QBL-GATE-02; M1 Scope).
- **Do not change the fast PR `make test` path** — keep it fast with `-m "not slow"`
  (M1 Scope "Out").
- **Do not fix the existing violations** — that is M2 (Phase 23) and M3 (Phase 24)
  (M1 Scope "Out").
- **Measure the coverage floor before setting it** — "Do not guess a number before
  measuring." Set `--cov-fail-under` ~2 points below the measured total. (M1 Steps; index.md
  Open questions).
- **Python commands use `uv run`** (project convention; Makefile uses `uv run` throughout).
- **Research/plan only — do not change code** (user instruction for this phase).

### the agent's Discretion
- Exact `test-full` target name and flags (the doc suggests `test-full`; `make test-cov`
  already exists and may be extended or kept separate).
- Nightly cron schedule time and whether to add `workflow_dispatch` (doc recommends both).
- Whether to scope per-file-ignores at file granularity (recommended; matches QBL-GATE-02
  and keeps the M2/M3 worklist precise) vs directory granularity.

### Deferred Ideas (OUT OF SCOPE)
- Fixing the 295 BLE001 / 97 T201 violations (Phases 23 / 24).
- Ratcheting the coverage floor upward over time (future, post-baseline).
- Any CLI decomposition, A/B suite, or benchmark work (Phases 25–27).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| QBL-GATE-01 | Ruff enables BLE001 and T20 so new broad-except/print debt is lint-gated | Verified current `select` list lacks BLE/T20; adding them flags 295 BLE001 + 97 T201. `make lint` runs `ruff check src` only (tests excluded). |
| QBL-GATE-02 | Existing violations captured as per-file ignores, not blanket disables | Full 96-file BLE001 list + 19-file T201 list captured below for `[tool.ruff.lint.per-file-ignores]`. Ruff per-file-ignores syntax verified. |
| QBL-GATE-03 | A full-suite coverage command exists for slow-inclusive coverage runs | Current `make test-cov` runs default (excludes `slow` via `addopts`), no fail-under. Need a `test-full` target that overrides the `-m "not slow"` default and adds `--cov-fail-under`. |
| QBL-GATE-04 | Nightly coverage workflow runs full suite with a measured fail-under floor | Existing `tests.yml` provides the exact uv/setup pattern to copy. Floor must be measured at execution time (2088 tests, 87 slow). YAML parse-check command documented. |
| QBL-GATE-05 | M2/M3 burn-down worklists derivable from lint config + source enumeration | The per-file-ignores tables *are* the worklist. Derivation commands documented so M2/M3 can re-enumerate and remove files as they are fixed. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Blind-except lint gate | Build/CI config (`pyproject.toml`) | CI runner (`make lint`) | Ruff config is the single source; `make lint` and the lint-format CI job enforce it. |
| Print-debt lint gate | Build/CI config (`pyproject.toml`) | CI runner | Same — `T20` lives in the ruff select list. |
| Per-file-ignore worklist | Build/CI config (`pyproject.toml`) | — | The ignore table doubles as the M2/M3 burn-down ledger. |
| Full-suite coverage command | Build tooling (`Makefile`) | — | A `test-full` target wraps pytest+coverage flags. |
| Nightly coverage enforcement | CI (`.github/workflows/`) | Build tooling | Scheduled workflow invokes the Makefile target with the floor. |

## Standard Stack

### Core (already installed — verified versions this session)
| Tool | Installed Version | Purpose | Why Standard |
|------|-------------------|---------|--------------|
| Ruff | **0.15.14** | Lint (BLE001, T201) | Already the project linter; `[tool.ruff.lint]` configured. |
| pytest | **9.0.3** | Test runner | Project standard; markers + addopts configured. |
| pytest-cov | **7.1.0** | Coverage + `--cov-fail-under` | Already a dev dependency; `make test-cov` uses it. |
| coverage.py | (bundled via pytest-cov) | Coverage measurement | Provides `--cov-fail-under` semantics. |

**No new packages are required for this phase.** All tooling is already present in the
`dev` dependency group and the `[dependency-groups] dev` table.

### Supporting (no install needed)
| Tool | Purpose | When to Use |
|------|---------|-------------|
| pytest-xdist 3.8 | Parallel test execution | Already used by `make test`; nightly may reuse `-n auto` to keep full-suite runtime bounded. |
| GitHub Actions `astral-sh/setup-uv@v5` | uv provisioning in CI | Copy verbatim from `tests.yml` for the nightly workflow. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `per-file-ignores` in pyproject | inline `# noqa: BLE001` per line | 392 inline edits = massive diff, defeats "no code change" constraint, harder to track as a worklist. Rejected. |
| `--cov-fail-under` flag | `[tool.coverage.report] fail_under` in pyproject | Config-file form applies to *all* coverage runs (incl. fast `test-cov`), which would break the fast path. Use the **flag** on the nightly target only. |
| New `nightly-coverage.yml` | Add a job to `tests.yml` | A separate file is cleaner for a `schedule:` trigger and matches the milestone doc's instruction. |

**Installation:** None. (Verify nothing drifted: `uv sync --frozen --group dev`.)

## Package Legitimacy Audit

> Not applicable — this phase installs **zero** external packages. All tools (ruff, pytest,
> pytest-cov, pytest-xdist) are already pinned in `pyproject.toml` and `uv.lock`. slopcheck
> gate skipped (nothing to check).

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │  pyproject.toml  [tool.ruff.lint]         │
   developer edit ──────▶│  select += "BLE","T20"                    │
                         │  per-file-ignores = { 96 BLE files,       │
                         │                       19 T201 files }     │
                         └───────────────┬───────────────────────────┘
                                         │
              ┌──────────────────────────┴───────────────────────────┐
              ▼ (PR path — fast)                       ▼ (nightly path — full)
   ┌───────────────────────┐                ┌──────────────────────────────┐
   │ make lint             │                │ .github/workflows/           │
   │  → ruff check src     │                │   nightly-coverage.yml       │
   │ make test             │                │   (schedule cron +           │
   │  → pytest -m not slow │                │    workflow_dispatch)        │
   │ (existing tests.yml)  │                │   → make test-full           │
   └───────────────────────┘                │      → pytest --cov=atelier  │
        NEW violations FAIL                 │        (slow incl.)          │
        existing → ignored                  │        --cov-fail-under=<F>  │
                                            └──────────────────────────────┘
                                                  coverage regression FAILS
```

### Recommended change surface
```
pyproject.toml
  [tool.ruff.lint]
    select          # add "BLE", "T20"
  [tool.ruff.lint.per-file-ignores]   # NEW table
    "src/.../file.py" = ["BLE001"]    # 96 entries
    "src/.../file.py" = ["T201"]      # 19 entries (some overlap → combined lists)

Makefile
  test-full:        # NEW — slow-inclusive coverage with fail-under

.github/workflows/
  nightly-coverage.yml   # NEW — schedule + workflow_dispatch → make test-full
```

### Pattern 1: Ruff `select` extension
**What:** Add rule families to the existing select list.
**Current** (verified `pyproject.toml` lines 106-108):
```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]
```
**Target:**
```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "BLE", "T20", "UP", "SIM", "RUF"]
ignore = ["E501"]
```
- `BLE` = flake8-blind-except → only rule is `BLE001`.
- `T20` = flake8-print → emits `T201` (print) and `T203` (pprint). Only `T201` occurs here.

### Pattern 2: per-file-ignores (the worklist)
**What:** Park existing violators so only new ones fail.
**Syntax** (ruff 0.15.x — glob keys relative to project root, value is list of codes):
```toml
[tool.ruff.lint.per-file-ignores]
"src/atelier/gateway/adapters/mcp_server.py" = ["BLE001", "T201"]
"src/atelier/__init__.py" = ["BLE001"]
# ...
```
A file that has **both** BLE001 and T201 violations gets both codes in one entry. The
combined source-of-truth lists are in the **Runtime State Inventory** section below.

### Pattern 3: Full-suite coverage Makefile target
**What:** A target that overrides the `-m "not slow"` default and adds the floor.
The existing `addopts` (line 116) is `-ra --strict-markers -m 'not slow'`, so default pytest
**deselects slow tests**. To include slow tests the target must pass `-m ""` (or
`-o addopts=` / `-m "slow or not slow"`) to override the marker filter.
```makefile
test-full: ## Run the FULL suite (incl. slow) with coverage floor
	uv run pytest -m "" --cov=atelier --cov-report=term-missing \
		--cov-fail-under=$(COV_FAIL_UNDER)
```
Note: `-m ""` clears the marker expression; verify it overrides `addopts` (alternatively
`--override-ini addopts=""` then re-add desired flags). Confirm during execution.

### Pattern 4: Nightly workflow (copy tests.yml idioms)
```yaml
name: Nightly coverage
on:
  schedule:
    - cron: "0 7 * * *"   # 07:00 UTC daily
  workflow_dispatch:
permissions:
  contents: read
defaults:
  run:
    shell: bash
jobs:
  coverage:
    runs-on: ubuntu-latest
    timeout-minutes: 40        # full suite incl. slow > the 20m PR budget
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --frozen --group dev
      - run: make test-full
```
(Action pin versions `checkout@v4`, `setup-python@v5`, `setup-uv@v5` taken verbatim from the
working `tests.yml`.)

### Anti-Patterns to Avoid
- **Blanket-disabling BLE001/T201 in `ignore`** — violates QBL-GATE-02; new debt would slip
  through. Use per-file-ignores.
- **Putting `fail_under` in `[tool.coverage.report]`** — it would gate the fast `test-cov`
  path too. Keep the floor on the nightly flag only.
- **Guessing the coverage number** — explicitly forbidden by the milestone. Measure first.
- **Linting `tests/`** — `make lint` runs `ruff check src` (PY_PATHS=src). Do NOT widen it
  to tests; test prints/excepts are intentional and out of scope.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting blind excepts | grep/regex audit script | Ruff `BLE001` | Ruff understands re-raise/`from` semantics; grep over-counts (337 vs 295). |
| Detecting stray prints | grep `print(` | Ruff `T201` | grep catches `.print()`, strings, comments (132 vs real 97). |
| Coverage floor enforcement | custom % parser | `pytest --cov-fail-under` | Built-in, exit-code aware, CI-native. |
| Worklist tracking | separate markdown TODO | the per-file-ignores table | The ignore table self-documents remaining debt; M2/M3 delete entries as fixed. |

**Key insight:** The lint rules are *more accurate than the grep baselines in the milestone
doc*. Trust `ruff check`, not the grep counts, when building the ignore list and the
M2/M3 worklist.

## Runtime State Inventory

> This is a config/CI phase, but it has a "stateful enumeration" dimension: the per-file
> ignore lists ARE captured runtime state that downstream phases consume. Captured below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Lint enumeration (BLE001) | **295 violations across 96 files** (verified `uv run ruff check src --select BLE001`). NOT 28 — the milestone's "28" counted only `except Exception: pass`; BLE001 flags all non-re-raising blind excepts. | Add all 96 files to per-file-ignores `["BLE001"]`. |
| Lint enumeration (T201) | **97 violations across 19 files** (verified `--select T20`). NOT 132 — grep over-counted. | Add all 19 files to per-file-ignores `["T201"]`. |
| Coverage floor | **Unmeasured** — must run full suite once at execution time. 2088 tests total (87 slow, 2001 not-slow). | Run `uv run pytest -m "" --cov=atelier`, record %, set floor ~2pts below. |
| Existing config | No `per-file-ignores` table exists; only 6 `# noqa` comments in src; `ignore = ["E501"]`. | New table is additive — no conflict. |
| Dirty worktree | 152 files modified/deleted in `git status` (incl. deleted `benchmarks/linear_vs_per_agent/`). | Coverage floor measured on dirty tree may differ from clean main; see Pitfall 1. |

**Nothing found in OS-registered state / secrets / build artifacts** — verified: this phase
changes only `pyproject.toml`, `Makefile`, and a new workflow file; no datastores, services,
env vars, or installed packages are renamed or migrated.

### Full BLE001 worklist (96 files — for `["BLE001"]`)
```
src/atelier/__init__.py
src/atelier/core/capabilities/autopilot/capability.py
src/atelier/core/capabilities/autopilot/factory.py
src/atelier/core/capabilities/budget_optimizer/optimizer.py
src/atelier/core/capabilities/code_context/engine.py
src/atelier/core/capabilities/code_context/intel_store.py
src/atelier/core/capabilities/context_compression/capability.py
src/atelier/core/capabilities/context_compression/deduplication.py
src/atelier/core/capabilities/context_reuse/capability.py
src/atelier/core/capabilities/lesson_promotion/capability.py
src/atelier/core/capabilities/local_recall.py
src/atelier/core/capabilities/loop_detection/capability.py
src/atelier/core/capabilities/memory_arbitration/arbiter.py
src/atelier/core/capabilities/model_routing/router.py
src/atelier/core/capabilities/optimization_audit.py
src/atelier/core/capabilities/plugin_runtime.py
src/atelier/core/capabilities/pricing.py
src/atelier/core/capabilities/registry/graph.py
src/atelier/core/capabilities/reporting/weekly_report.py
src/atelier/core/capabilities/savings_summary.py
src/atelier/core/capabilities/semantic_file_memory/capability.py
src/atelier/core/capabilities/semantic_file_memory/python_ast.py
src/atelier/core/capabilities/semantic_file_memory/treesitter_ast.py
src/atelier/core/capabilities/semantic_file_memory/typescript_ast.py
src/atelier/core/capabilities/style_import/importer.py
src/atelier/core/capabilities/sync/sync_engine.py
src/atelier/core/capabilities/telemetry/context_budget.py
src/atelier/core/capabilities/tool_supervision/bash_exec.py
src/atelier/core/capabilities/tool_supervision/batch_edit.py
src/atelier/core/capabilities/tool_supervision/capability.py
src/atelier/core/capabilities/tool_supervision/native_search.py
src/atelier/core/capabilities/tool_supervision/rich_edit.py
src/atelier/core/capabilities/tool_supervision/search_read.py
src/atelier/core/capabilities/tool_supervision/smart_search.py
src/atelier/core/capabilities/verification/checks/lint.py
src/atelier/core/capabilities/verification/checks/tests.py
src/atelier/core/capabilities/verification/checks/typecheck.py
src/atelier/core/domains/loader.py
src/atelier/core/domains/manager.py
src/atelier/core/environment.py
src/atelier/core/foundation/identity.py
src/atelier/core/foundation/rubric_gate.py
src/atelier/core/foundation/store.py
src/atelier/core/foundation/watchdog_profiles.py
src/atelier/core/runtime/engine.py
src/atelier/core/service/api.py
src/atelier/core/service/ingest_session.py
src/atelier/core/service/ingest_session_directory.py
src/atelier/core/service/sync.py
src/atelier/core/service/telemetry/__init__.py
src/atelier/core/service/telemetry/config.py
src/atelier/core/service/telemetry/emit.py
src/atelier/core/service/telemetry/exporters/otel.py
src/atelier/core/service/worker.py
src/atelier/gateway/adapters/mcp_server.py
src/atelier/gateway/adapters/remote_client.py
src/atelier/gateway/cli/app.py
src/atelier/gateway/hosts/registry.py
src/atelier/gateway/hosts/session_parsers/_common.py
src/atelier/gateway/hosts/session_parsers/_session_parser.py
src/atelier/gateway/hosts/session_parsers/claude.py
src/atelier/gateway/hosts/session_parsers/cline.py
src/atelier/gateway/hosts/session_parsers/codex.py
src/atelier/gateway/hosts/session_parsers/copilot.py
src/atelier/gateway/hosts/session_parsers/gemini.py
src/atelier/gateway/hosts/session_parsers/opencode.py
src/atelier/gateway/integrations/external_analytics.py
src/atelier/gateway/integrations/langfuse.py
src/atelier/gateway/integrations/ledger_reconstructor.py
src/atelier/gateway/integrations/openmemory.py
src/atelier/infra/code_intel/git_history/adapter.py
src/atelier/infra/code_intel/git_history/walker.py
src/atelier/infra/code_intel/zoekt/adapter.py
src/atelier/infra/embeddings/factory.py
src/atelier/infra/memory_bridges/letta_adapter.py
src/atelier/infra/memory_bridges/openmemory.py
src/atelier/infra/runtime/checkpoint.py
src/atelier/infra/runtime/context_compressor.py
src/atelier/infra/runtime/insights.py
src/atelier/infra/runtime/outcome_capture.py
src/atelier/infra/runtime/realtime_context.py
src/atelier/infra/runtime/session_state.py
src/atelier/infra/storage/postgres_store.py
src/atelier/infra/storage/sqlite_store.py
src/atelier/infra/tree_sitter/tags.py
src/atelier/sdk/anthropic_tools.py
src/atelier/sdk/gemini_adk.py
src/atelier/sdk/langchain_middleware.py
src/benchmarks/swe/compact_bench.py
src/benchmarks/swe/compact_quality_bench.py
src/benchmarks/swe/routing_bench.py
src/benchmarks/swe/routing_quality_bench.py
src/benchmarks/swe/routing_replay_bench.py
src/benchmarks/swe/savings_replay.py
src/benchmarks/tool_bench/report.py
src/benchmarks/tool_bench/runner.py
```

### Full T201 worklist (19 files — for `["T201"]`)
```
src/atelier/gateway/adapters/mcp_server.py
src/atelier/gateway/hosts/registry.py
src/atelier/gateway/hosts/session_parsers/_common.py
src/atelier/gateway/hosts/session_parsers/claude.py
src/atelier/gateway/hosts/session_parsers/cline.py
src/atelier/gateway/hosts/session_parsers/codex.py
src/atelier/gateway/hosts/session_parsers/copilot.py
src/atelier/gateway/hosts/session_parsers/gemini.py
src/atelier/gateway/hosts/session_parsers/goose.py
src/atelier/gateway/hosts/session_parsers/kiro.py
src/atelier/gateway/hosts/session_parsers/opencode.py
src/atelier/infra/benchmarks/publisher.py
src/benchmarks/code_intel/scale_decision_eval.py
src/benchmarks/swe/routing_replay_bench.py
src/benchmarks/swe/savings_bench.py
src/benchmarks/swe/savings_replay.py
src/benchmarks/swe/swebench_eval.py
src/benchmarks/tool_bench/__main__.py
src/benchmarks/tool_bench/report.py
```

**Files needing BOTH codes** (intersection — combine into one entry with `["BLE001","T201"]`):
`mcp_server.py`, `hosts/registry.py`, `session_parsers/_common.py`, `claude.py`, `cline.py`,
`codex.py`, `copilot.py`, `gemini.py`, `opencode.py`, `benchmarks/swe/routing_replay_bench.py`,
`benchmarks/swe/savings_replay.py`, `benchmarks/tool_bench/report.py`.

### Derivation commands (QBL-GATE-05 — re-runnable for M2/M3)
```bash
# BLE001 file list
uv run ruff check src --select BLE001 --output-format=concise | grep -oE "^src/[^:]+" | sort -u
# T201 file list
uv run ruff check src --select T20 --output-format=concise | grep -oE "^src/[^:]+" | sort -u
# Per-file violation counts (prioritization)
uv run ruff check src --select BLE001 --output-format=concise | grep -oE "^src/[^:]+" | sort | uniq -c | sort -rn
```

## Common Pitfalls

### Pitfall 1: Coverage floor measured on a dirty worktree
**What goes wrong:** `git status` shows 152 modified/deleted files. Coverage measured now
differs from coverage on clean `main`, and the nightly CI runs on `main`.
**Why it happens:** The repo has substantial uncommitted work (STATE.md Watch Point:
"Uncommitted implementation changes").
**How to avoid:** Measure the floor in CI (or on a clean checkout) for the number that the
nightly job will actually enforce, OR set the floor conservatively (~2 pts below measured)
so worktree drift does not cause false failures. Document which environment produced the
number.
**Warning signs:** Floor passes locally but nightly fails on first run.

### Pitfall 2: `addopts = -m 'not slow'` silently excludes slow tests from coverage
**What goes wrong:** A naive `pytest --cov` (or the existing `make test-cov`) inherits the
`-m 'not slow'` default and measures coverage **without the 87 slow tests** — inflating or
deflating the number and defeating QBL-GATE-03's "slow-inclusive" requirement.
**Why it happens:** `[tool.pytest.ini_options] addopts` (line 116) applies to every pytest
invocation.
**How to avoid:** The `test-full` target must explicitly override the marker filter
(`-m ""` or `--override-ini "addopts=..."`). Verify with `pytest --collect-only -m ""`
shows 2088, not 2001.
**Warning signs:** `make test-full` collects 2001 tests instead of 2088.

### Pitfall 3: `ignore` vs `per-file-ignores` confusion
**What goes wrong:** Adding `BLE001` to the top-level `ignore` list disables it everywhere —
new debt slips through, violating QBL-GATE-02.
**How to avoid:** Only touch `[tool.ruff.lint.per-file-ignores]`. Leave top-level `ignore`
as `["E501"]`.
**Warning signs:** `make lint` passes even after introducing a new `except Exception: pass`
in a clean file.

### Pitfall 4: YAML workflow does not parse / wrong schema
**What goes wrong:** A malformed `nightly-coverage.yml` is silently ignored by GitHub or
fails to schedule.
**How to avoid:** Run the milestone's parse check:
`uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/nightly-coverage.yml'))"`.
Also `actionlint` if available. Confirm `schedule.cron` is quoted and 5-field.
**Warning signs:** Workflow never appears under Actions tab; no nightly runs.

### Pitfall 5: Nightly full-suite timeout
**What goes wrong:** The PR `test` job uses `timeout-minutes: 20` and `-n auto`. The full
suite (slow incl.) may exceed 20 min serially.
**How to avoid:** Give the nightly job a larger `timeout-minutes` (e.g., 40) and consider
reusing `-n auto --dist=loadfile` like `make test` does. Measure the full-suite wall time
during execution.
**Warning signs:** Nightly job killed at the timeout boundary.

### Pitfall 6: Postgres/worker-gated slow tests need services
**What goes wrong:** `make test-fast` explicitly ignores `tests/test_postgres_store.py` and
`tests/test_worker_jobs.py`. Some slow tests may need a live Postgres that CI lacks.
**How to avoid:** Check whether the full suite's slow tests require external services; if so,
either provision them in the nightly workflow or keep those specific files excluded with a
documented rationale. Investigate during execution.
**Warning signs:** Nightly fails on connection errors, not assertion failures.

## Code Examples

### Verify the new rules flag what we expect (run before/after editing pyproject)
```bash
# Source: this session, ruff 0.15.14
uv run ruff check src --select BLE001 --output-format=concise | wc -l   # → 295
uv run ruff check src --select T20    --output-format=concise | wc -l   # → 97
```

### Local dry-run of the nightly gate
```bash
# Measure floor (slow-inclusive)
uv run pytest -m "" --cov=atelier --cov-report=term-missing | tail -5
# Then enforce a candidate floor
uv run pytest -m "" --cov=atelier --cov-fail-under=<FLOOR>
```

### Confirm fast PR path is unchanged
```bash
uv run pytest --collect-only -m "not slow" -q | tail -1   # → 2001 collected
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `[tool.ruff] select` | `[tool.ruff.lint] select` | ruff 0.2+ | Repo already uses the `lint` subtable — correct for 0.15.x. |
| `flake8-blind-except` plugin | Ruff `BLE` | native | One tool; no extra deps. |
| `flake8-print` plugin | Ruff `T20` | native | Same. |

**Deprecated/outdated:** Milestone doc's grep baselines (28 / 132) are *measurement
heuristics*, not the lint truth (295 / 97). Use ruff output for the worklist.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `-m ""` reliably overrides the `addopts` marker filter to include slow tests | Pattern 3 / Pitfall 2 | If pytest merges rather than overrides, slow tests stay excluded; use `--override-ini` instead. Verify at execution. |
| A2 | Slow tests do not require unavailable external services in CI | Pitfall 6 | Nightly may fail on missing Postgres; may need service containers or targeted excludes. |
| A3 | `cron: "0 7 * * *"` is an acceptable nightly time | Pattern 4 | Cosmetic; user/discretion may prefer another hour. |
| A4 | Coverage floor of "measured −2pts" is the intended policy | User Constraints | Milestone says "~2 points below"; treated as guidance, confirm exact value after measuring. |

## Open Questions (RESOLVED BY PLAN)

1. **What is the actual full-suite coverage %?**
   - What we know: 2088 tests, 87 slow; command is known.
   - What's unclear: the number — must be measured on a clean/CI checkout (worktree dirty).
   - Resolution: Task 2 measures coverage during execution and sets the floor ~2 pts below the observed total.

2. **Do any slow tests need external services in nightly CI?**
   - What we know: `make test-fast` excludes postgres + worker tests.
   - What's unclear: whether those run under `slow` and need services.
   - Resolution: Task 2 records any slow-test service limitations in the SUMMARY for CI confirmation.

3. **Should the nightly job parallelize (`-n auto`)?**
   - Resolution: Task 3 delegates to `make test-full`; Task 2 owns whether the target needs xdist or an override-ini fallback after collection/coverage measurement.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ruff | BLE001/T201 gates | ✓ | 0.15.14 | — |
| pytest | coverage run | ✓ | 9.0.3 | — |
| pytest-cov | `--cov-fail-under` | ✓ | 7.1.0 | — |
| pytest-xdist | nightly parallelism | ✓ | 3.8 | serial run |
| uv | all commands | ✓ | (repo standard) | — |
| GitHub Actions | nightly schedule | ✓ (3 workflows exist) | — | — |
| PyYAML | workflow parse-check | ✓ (`pyyaml>=6.0` dep) | — | — |

**Missing dependencies with no fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-cov 7.1.0 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=`tests`, addopts=`-ra --strict-markers -m 'not slow'`) |
| Quick run command | `uv run pytest -m "not slow" -q` (2001 tests) |
| Full suite command | `uv run pytest -m "" --cov=atelier --cov-fail-under=<FLOOR>` (2088 tests, 87 slow) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QBL-GATE-01 | New BLE001/T201 violation fails lint | smoke | `make lint` after injecting a temp blind-except in a clean file → expect failure | ✅ uses existing `make lint` |
| QBL-GATE-01 | Rules are selected | unit | `uv run ruff check src --select BLE001,T20 \| tail -1` shows counts | ✅ |
| QBL-GATE-02 | Existing violators pass via per-file-ignores | smoke | `make lint` exits 0 with the new table | ✅ |
| QBL-GATE-02 | No blanket disable | grep | `grep -A2 '\[tool.ruff.lint\]' pyproject.toml` — `ignore` still `["E501"]` only | ✅ |
| QBL-GATE-03 | Full-suite coverage target exists & is slow-inclusive | smoke | `make test-full` collects 2088 (not 2001) | ❌ Wave 0 (add `test-full`) |
| QBL-GATE-04 | Nightly workflow parses & has schedule + floor | unit | `uv run python -c "import yaml; d=yaml.safe_load(open('.github/workflows/nightly-coverage.yml')); assert 'schedule' in d['on'] or 'schedule' in d[True]"` | ❌ Wave 0 (add workflow) |
| QBL-GATE-05 | Worklist derivable from config | smoke | ruff enumeration commands return the 96/19 file lists matching pyproject | ✅ |

### Sampling Rate
- **Per task commit:** `make lint` (fast) + the relevant ruff `--select` enumeration.
- **Per wave merge:** `make lint && make typecheck && uv run pytest -m "not slow" -q`.
- **Phase gate:** full `make lint && make typecheck && make test`, plus one
  `make test-full` dry-run confirming the floor passes, plus YAML parse-check.

### Wave 0 Gaps
- [ ] `Makefile` — add `test-full` target (slow-inclusive coverage + `--cov-fail-under`).
- [ ] `.github/workflows/nightly-coverage.yml` — new scheduled workflow.
- [ ] One measured coverage number → fill `<FLOOR>` (execution step, not a file).
- [ ] (Optional) a tiny smoke test asserting the per-file-ignores table covers all current
      violators so a future fix that removes a file from source doesn't leave a stale ignore.

## Security Domain

> `security_enforcement` not set false in config → included. This phase is CI/config only.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | no | — (no runtime code) |
| V6 Cryptography | no | — |
| V14 Configuration | yes | Workflow `permissions: contents: read` (least privilege), pinned action versions, `uv sync --frozen`. |

### Known Threat Patterns for CI config
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Over-privileged workflow token | Elevation | `permissions: contents: read` (copy from tests.yml). |
| Unpinned/compromised action | Tampering | Pin `@v4`/`@v5` tags as existing workflows do; consider SHA pinning. |
| Dependency drift in CI | Tampering | `uv sync --frozen` against `uv.lock`. |

## Sources

### Primary (HIGH confidence)
- Repo tools run this session: `ruff 0.15.14`, `pytest 9.0.3`, `pytest-cov 7.1.0` —
  version + violation counts verified directly.
- `pyproject.toml` (lines 102-152) — ruff/pytest/coverage config.
- `Makefile` (lines 82-124) — lint/test/test-cov/typecheck targets.
- `.github/workflows/tests.yml` — CI pattern (uv setup, job structure, permissions).
- `docs/plans/quality-and-benchmark-lift/index.md` + `M1-lint-and-coverage-gates.md` —
  milestone source of truth.
- `.planning/REQUIREMENTS.md` (QBL-GATE-01..05), `.planning/STATE.md` (decisions).

### Secondary (MEDIUM confidence)
- Ruff rule semantics (BLE001 = flake8-blind-except; T20 = flake8-print T201/T203) —
  training knowledge consistent with observed output.

### Tertiary (LOW confidence)
- A1 (`-m ""` override behavior) — assumed; verify at execution.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified by running the tools.
- Architecture / config changes: HIGH — surfaces and current config read directly.
- Violation enumeration: HIGH — produced by ruff this session.
- Coverage floor: N/A — must be measured at execution (cannot pre-determine).
- Pytest marker-override mechanic: MEDIUM — needs execution-time confirmation.

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (stable tooling; re-enumerate violation counts if src changes).

## RESEARCH COMPLETE

**Phase:** 22 - Lint and Coverage Gates
**Confidence:** HIGH

### Key Findings
- Milestone grep baselines are misleading: Ruff flags **295 BLE001 across 96 files** and
  **97 T201 across 19 files** (not 28 / 132). Full file lists captured for per-file-ignores.
- No new packages needed — ruff 0.15.14, pytest 9.0.3, pytest-cov 7.1.0 already present.
- `make lint` lints `src` only; the fast `addopts = -m 'not slow'` default silently excludes
  87 slow tests — the new `test-full` target must override it (`-m ""`).
- Coverage floor must be **measured at execution** (2088 tests; worktree is dirty with 152
  changed files — measure on clean/CI checkout). Floor goes on the nightly flag only, never
  in `[tool.coverage.report]`.
- Nightly workflow can copy `tests.yml` idioms verbatim (uv setup, pinned actions,
  least-privilege permissions); needs larger timeout + YAML parse check.

### File Created
`.planning/phases/22-lint-and-coverage-gates/22-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | Versions verified by running tools. |
| Architecture | HIGH | Config/Makefile/workflow read directly. |
| Pitfalls | HIGH | Derived from observed config + enumerations. |

### Open Questions (RESOLVED BY PLAN)
- Exact full-suite coverage % — resolved by Task 2 execution-time measurement.
- Whether slow tests need external services in nightly CI — resolved by Task 2 SUMMARY recording if local/CI services are unavailable.
- Confirm `-m ""` overrides `addopts` — resolved by Task 2 collect-only check with `--override-ini` fallback.

### Ready for Planning
Research complete. Planner can now create PLAN.md files.
