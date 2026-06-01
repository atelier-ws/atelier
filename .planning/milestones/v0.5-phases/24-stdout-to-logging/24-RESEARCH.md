# Phase 24: Stdout to Logging - Research

**Researched:** 2026-05-29
**Domain:** Python logging hygiene / MCP JSON-RPC stdio framing integrity / Ruff T20 burn-down
**Confidence:** HIGH (inventory + classification verified directly against the working tree with AST and `ruff`)

## Summary

Phase 24 converts stray non-CLI `print()` calls to module logging or stderr diagnostics so the
MCP stdio server (`atelier-mcp`) never leaks non-protocol bytes onto stdout, where they would
corrupt JSON-RPC framing. The milestone design doc (M3) cites "132 sites"; that figure counts raw
`grep "print("` substring matches. The **authoritative live count is 97 `print()` calls across 19
files** — confirmed by both an AST walk (`ast.Call` with `func.id == "print"`) and
`ruff check src --select T20` (both return exactly 97). The 35-file `grep` count is inflated by
substring false positives (`_fingerprint`, `ensure_dependency_or_print`) and `print()` examples
inside docstrings (which T20 correctly ignores). `[VERIFIED: AST walk + ruff 0.15.14]`

The good news for sequencing: **every one of the 19 T201-bearing per-file-ignore entries in
`pyproject.toml` maps 1:1 to a live print site — none are stale.** The work splits cleanly into
three buckets: (1) **non-CLI library/infra/server** code that must convert to loggers (the real
debt — `registry.py`, the 8 session-parser modules, `infra/benchmarks/publisher.py`, and the
single `mcp_server.py` `--version` print), and (2) **benchmark dev-CLI entry points** under
`src/benchmarks/**` whose stdout output is legitimate and should stay ignored, and (3) the actual
CLI package `gateway/cli/app.py`, which **has zero T201 violations today** — it already uses
`click.echo` (511 call sites). So QBL-LOG-03 ("CLI uses click.echo, remains ignored by T20") is
already satisfied for `cli/app.py`; the boundary work is about benchmark tooling, not the CLI.

The one genuine risk concentrated in a single line is `mcp_server.py:5456` —
`print(f"atelier-mcp {SERVER_VERSION}")`. It sits inside `main()` behind a `--version`/`-V` guard
and `return`s *before* the JSON-RPC stdio loop starts, so it does not currently corrupt framing.
But it lives in the MCP entry-point file and is the last thing standing between
`mcp_server.py` and a `T201`-clean entry. The session-parser progress prints
(`[atelier] ... importing i/total`) are reachable **only** from `cli/app.py`'s `import` command
(`import_all`), never from the MCP server process — verified by call-graph grep.

**Primary recommendation:** Convert the ~33 non-benchmark prints to module loggers
(`logging.getLogger(__name__)`, which several files already have), preserve user-visible CLI import
progress by routing those logger records to **stderr** (add a small stderr `StreamHandler` in the
CLI `import` path — *not* a CLI decomposition, which is Phase 25), keep `src/benchmarks/**` print
output as an intentional ignored boundary, drop/shrink the 12 now-clean T201 ignore entries, and
harden the MCP stdio smoke test to assert **every** stdout line parses as a JSON object.

## User Constraints

No `CONTEXT.md` exists for this phase (not yet discussed). The following constraints come from the
phase brief and project instructions and are binding on the planner:

### Locked Constraints
- Python commands MUST use `uv run` (CLAUDE.md / AGENTS.md). `python3` directly is wrong env.
- **Do NOT propose broad CLI decomposition** — Phase 25 (QBL-CLI-01–04) owns moving command groups
  out of `gateway/cli/app.py`. Phase 24 may add a *minimal* logging handler to the import path but
  must not restructure the CLI.
- Do NOT modify source code during research (this report only; no fixes applied).
- The working tree is **dirty (184 changed/deleted paths)** and has documented baseline failures
  (see Known Baseline below). These are NOT Phase 24 work and must not be "fixed" by this phase.

### the agent's Discretion
- Whether benchmark dev-CLI prints (`src/benchmarks/**`) are scoped out via a directory-level
  ignore vs. retained as individual per-file-ignores (both presented below).
- Whether the `mcp_server.py --version` print becomes `sys.stdout.write(...)`, a `# noqa: T201`
  with rationale, or stays inside a retained ignore.
- Logger level choice per converted call (`debug` vs `info` vs `warning`).

### Deferred Ideas (OUT OF SCOPE)
- CLI command-group extraction → Phase 25.
- Converting benchmark report renderers to structured output → not required by QBL-LOG-*.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| QBL-LOG-01 | Fresh enumeration of `print()` in `src/` bucketed CLI-allowed vs non-CLI debt | Fresh AST+ruff inventory below: 97 calls / 19 files, classified into 3 buckets |
| QBL-LOG-02 | Non-CLI core/infra/server/background prints → module logging or stderr diagnostics | Per-file fix table; 8 session parsers + `registry.py` + `publisher.py` + `mcp_server.py` |
| QBL-LOG-03 | CLI user output uses `click.echo`, remains ignored by T20 | `cli/app.py` already T201-clean (511 `click.echo`); boundary = `src/benchmarks/**` |
| QBL-LOG-04 | MCP stdio smoke tests confirm no non-protocol stdout leaks | `test_mcp_stdio_smoke.py` exists but is lenient — hardening plan below |

## Project Constraints (from CLAUDE.md / AGENTS.md)

- `uv run` for all Python (`uv run pytest`, `uv run ruff`, `uv run mypy`, `uv run atelier`).
- Three-layer dependency direction: `gateway/ → core/ → infra/`. Loggers belong at module level
  per file; do not introduce cross-layer logging dependencies.
- `mcp_server.py` / `cli.py` are dispatchers only — do not add new capabilities there.
- `make lint` = `ruff check src`; `make typecheck` = `mypy --strict src`; `make test` = pytest
  (slow excluded by default via `addopts = -m 'not slow'`).
- Generated files (`AGENTS.md`, `copilot-instructions.md`) must not be hand-edited.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MCP JSON-RPC protocol I/O | `gateway/adapters/mcp_server.py` | — | stdout is the protocol channel; only framed JSON-RPC allowed |
| MCP diagnostic logging | `infra` (file handler) | — | `_setup_file_logging` already routes `atelier.mcp` → `~/.atelier/mcp/mcp.log`, never stdout `[VERIFIED]` |
| CLI user output | `gateway/cli/app.py` | — | `click.echo` to stdout is legitimate user output |
| Session import progress | `gateway/hosts/session_parsers/*` (library) | `gateway/cli` (invokes) | Library modules → log; CLI surfaces progress on stderr |
| Benchmark/eval result output | `src/benchmarks/**` (standalone CLIs) | — | Dev tooling; stdout is the intended report channel, never MCP-reachable |
| Host registry persistence | `gateway/hosts/registry.py` | — | Load failures are infra warnings → logger, not stdout |

## Standard Stack

No new packages are required. Everything needed is stdlib or already a dependency.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `logging` (stdlib) | py3.11 | Module loggers, stderr `StreamHandler`, file handlers | Already the project's logging mechanism (`atelier.mcp` file logger) `[VERIFIED]` |
| `click` | >=8.1 (installed) | CLI user-facing output via `click.echo(..., err=True)` for stderr | Project standard; 511 `click.echo` sites already in `cli/app.py` `[VERIFIED: pyproject]` |
| `sys.stderr` (stdlib) | py3.11 | Direct diagnostic stream when a logger is overkill | Standard escape hatch for "must reach TTY, never stdout" |

### Tooling (already present)
| Tool | Version | Purpose |
|------|---------|---------|
| `ruff` | 0.15.14 | `T20` (T201/T203) print detection; the burn-down ledger `[VERIFIED]` |
| `pytest` | 9.0.3 | stdio smoke + e2e framing tests `[VERIFIED]` |
| `mypy` | strict | type gate (unchanged by logging conversion) |

**Installation:** none — no `pip install` / dependency changes.

## Package Legitimacy Audit

**Not applicable.** Phase 24 installs no external packages. All mechanisms (`logging`, `sys`,
`click`) are stdlib or pre-existing dependencies verified in `pyproject.toml`. No slopcheck run
required.

## Fresh Inventory — All 97 `print()` Sites (T20, ignores disabled)

> Source: `uv run ruff check src --select T20 --config 'lint.per-file-ignores={}'` AND an
> independent `ast` walk — both return 97 calls / 19 files exactly. `[VERIFIED: ruff 0.15.14 + AST]`

| # | File | Sites | Lines | Bucket | MCP-stdio reachable? |
|---|------|-------|-------|--------|----------------------|
| 1 | `gateway/adapters/mcp_server.py` | 1 | 5456 | **MCP entry-point** (`--version`, returns before stdio loop) | In-process, **pre-loop only** |
| 2 | `gateway/hosts/registry.py` | 1 | 141 | **Non-CLI infra** (load-failure warning) | No |
| 3 | `gateway/hosts/session_parsers/_common.py` | 4 | 748,754,757,765 | Library progress (CLI import) | No |
| 4 | `gateway/hosts/session_parsers/claude.py` | 4 | 222,229,232,238 | Library progress | No |
| 5 | `gateway/hosts/session_parsers/cline.py` | 4 | 204,211,220,223 | Library progress | No |
| 6 | `gateway/hosts/session_parsers/codex.py` | 5 | 312,317,320,330,332 | Library progress | No |
| 7 | `gateway/hosts/session_parsers/copilot.py` | 10 | 393,404,413,423,432,438,447,456,784,950 | Library progress | No |
| 8 | `gateway/hosts/session_parsers/gemini.py` | 4 | 152,159,163,172 | Library progress | No |
| 9 | `gateway/hosts/session_parsers/goose.py` | 2 | 71,74 | Library progress | No |
| 10 | `gateway/hosts/session_parsers/kiro.py` | 2 | 84,88 | Library progress | No |
| 11 | `gateway/hosts/session_parsers/opencode.py` | 2 | 80,84 | Library progress | No |
| 12 | `infra/benchmarks/publisher.py` | 2 | 336,338 | **Non-CLI infra** (`_print_dry_run`) | No |
| 13 | `benchmarks/code_intel/scale_decision_eval.py` | 1 | 321 | Benchmark dev-CLI | No |
| 14 | `benchmarks/swe/routing_replay_bench.py` | 2 | 538,547 | Benchmark dev-CLI | No |
| 15 | `benchmarks/swe/savings_bench.py` | 2 | 333,335 | Benchmark dev-CLI | No |
| 16 | `benchmarks/swe/savings_replay.py` | 1 | 603 | Benchmark dev-CLI | No |
| 17 | `benchmarks/swe/swebench_eval.py` | 2 | 48,126 | Benchmark dev-CLI | No |
| 18 | `benchmarks/tool_bench/__main__.py` | 4 | 100–103 | Benchmark dev-CLI | No |
| 19 | `benchmarks/tool_bench/report.py` | 44 | 91–462 | Benchmark dev-CLI report renderer | No |

**Bucket totals:** MCP entry-point 1 · Non-CLI infra/library 38 (registry 1 + parsers 37... wait
counts: registry 1, parsers 4+4+4+5+10+4+2+2+2 = 37, publisher 2 = **40 non-CLI debt**) · benchmark
dev-CLI 56 (1+2+2+1+2+4+44).

### False positives explicitly excluded (do NOT touch)
- `cli/app.py` — grep matched `print(` but **AST/ruff find 0 T201**: it uses `click.echo`. Already
  compliant with QBL-LOG-03. `[VERIFIED]`
- `infra/runtime/insights.py:11`, `infra/runtime/session_report.py:12,17` — `print(render_text(...))`
  appears inside module **docstring** `Usage::` examples, not executable code; T20 correctly skips.
  No fix, no ignore needed. `[VERIFIED: viewed source]`
- `budget_optimizer/optimizer.py:30`, `cross_vendor_memory/{__init__,audit_log,registry}.py`,
  `monitors/{fsm,suite}.py`, `prefix_cache/diagnostics.py` — all `print(...)` inside docstring
  examples. `[VERIFIED]`
- `failure_analysis/capability.py`, `plugin_runtime.py`, `style_import/importer.py`,
  `improvement/failure_analyzer.py`, `hosts/models.py`, `swe/run_swe_bench.py` — grep hit substrings
  `_fingerprint` / `ensure_dependency_or_print` / `HostFingerprint`, **not** print calls. `[VERIFIED]`

## Classification & Recommended Fix

| Bucket | Files | Recommended fix | T201 ignore disposition |
|--------|-------|-----------------|-------------------------|
| **MCP entry-point** | `mcp_server.py:5456` | Replace with `sys.stdout.write(f"atelier-mcp {SERVER_VERSION}\n")` (still pre-loop, but clears T201) — OR keep `print` + `# noqa: T201  # version flag exits before stdio loop`. Module logger `_log` already exists and is file-routed. | `["BLE001","T201"]` → `["BLE001"]` (drop T201) |
| **Non-CLI infra warning** | `registry.py:141` | `logger.warning("Failed to load %s: %s", file, e, exc_info=True)` (add `logger = logging.getLogger(__name__)`; narrow the bare `except` per Phase-23 pattern if still broad) | `["BLE001","T201"]` → `["BLE001"]` |
| **Non-CLI infra dry-run** | `publisher.py:336,338` | `logger.info(...)` (add module logger) — OR have the CLI `benchmark publish` command emit the dry-run lines via `click.echo`. Library module should not print. | `["T201"]` → **remove entry** |
| **Library import progress** | 8 `session_parsers/*` + `_common.py` | Convert to `logger.info(...)` / `logger.debug(...)`. `_common.py` already has `logger` (line 27); `claude/cline/codex/copilot/gemini/goose/kiro/opencode` need `logger = logging.getLogger(__name__)` added. **Preserve user visibility:** add a stderr `StreamHandler` at INFO on the `atelier.gateway.hosts` (or root `atelier`) logger inside the CLI `import` command path (small, not decomposition). | combined files → `["BLE001"]`; `goose`/`kiro` (`["T201"]`) → **remove entry** |
| **Benchmark dev-CLI** | `src/benchmarks/**` (7 files, 56 prints) | **Keep stdout output** — these are standalone `python -m` benchmark CLIs whose stdout is the intended report channel and are never imported by the MCP server. This IS the "intended CLI/non-CLI boundary" (QBL-LOG-03). Optionally migrate to `click.echo` for consistency, but not required. | **Retain** (see ignore plan for per-file vs directory-glob options) |

### Why stderr (not stdout) for converted CLI progress
The M3 design doc is explicit: *"Diagnostics that must reach a user on a TTY go to stderr, never
stdout, in server contexts."* Converting to a module logger + a CLI-configured stderr handler keeps
import progress visible to the human running `atelier import` while guaranteeing stdout stays clean
regardless of any future caller (including a hypothetical MCP import tool). **Caveat the planner
must handle:** the CLI currently does **not** call `logging.basicConfig` or attach any handler
(`cli/app.py` only does `logger = getLogger(__name__)`) — so a naive `logger.info()` conversion
would make progress *silently disappear* (records propagate to a handler-less root at WARNING).
The conversion MUST be paired with an explicit stderr handler attached in the import command.
`[VERIFIED: grep of cli/app.py shows no basicConfig/StreamHandler]`

## T201 Ignore Shrink Plan

Current `[tool.ruff.lint.per-file-ignores]` carries **19 T201-bearing entries**, all matching live
sites (no stale entries — re-derive with the command in the pyproject comment). After Phase 24:

### Remove T201 (9 entries demote `["BLE001","T201"]` → `["BLE001"]`)
- `gateway/adapters/mcp_server.py`
- `gateway/hosts/registry.py`
- `gateway/hosts/session_parsers/_common.py`
- `gateway/hosts/session_parsers/claude.py`
- `gateway/hosts/session_parsers/cline.py`
- `gateway/hosts/session_parsers/codex.py`
- `gateway/hosts/session_parsers/copilot.py`
- `gateway/hosts/session_parsers/gemini.py`
- `gateway/hosts/session_parsers/opencode.py`

### Remove entry entirely (3 T201-only entries become empty)
- `gateway/hosts/session_parsers/goose.py`
- `gateway/hosts/session_parsers/kiro.py`
- `infra/benchmarks/publisher.py`

### Retain (7 benchmark dev-CLI entries — intentional boundary)
- `benchmarks/swe/routing_replay_bench.py` (`["BLE001","T201"]` — keep both)
- `benchmarks/swe/savings_replay.py` (`["BLE001","T201"]` — keep both)
- `benchmarks/tool_bench/report.py` (`["BLE001","T201"]` — keep both)
- `benchmarks/code_intel/scale_decision_eval.py` (`["T201"]`)
- `benchmarks/swe/savings_bench.py` (`["T201"]`)
- `benchmarks/swe/swebench_eval.py` (`["T201"]`)
- `benchmarks/tool_bench/__main__.py` (`["T201"]`)

**Net T201 result:** 19 → 7 entries (all under `src/benchmarks/**`). 12 entries cleared.

### Boundary-encoding option (the agent's discretion)
Instead of 7 per-file benchmark ignores, the planner may collapse them to a single directory glob
that documents intent more clearly:
```toml
# Benchmark dev-CLIs print results to stdout by design; never imported by the MCP server.
"src/benchmarks/**/*.py" = ["T201"]
```
Trade-off: cleaner intent + future-proof for new benchmark files, but slightly broader than the
exact current set (would also silence T201 in benchmark files that don't have it yet). The
BLE001 entries on `routing_replay_bench.py`, `savings_replay.py`, `report.py` must be preserved
separately either way. **Verify after** with the re-derive command in pyproject and confirm
`ruff check src` stays green.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 `[VERIFIED]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`; `addopts = "-ra --strict-markers -m 'not slow'"` |
| Quick run command | `uv run pytest tests/gateway/test_p0_mcp_surfaces.py -q` |
| Full / slow MCP stdio | `uv run pytest tests/gateway/test_mcp_stdio_smoke.py tests/gateway/test_mcp_jsonrpc_e2e.py -m "" -q` |
| Lint gate | `uv run ruff check src` (must be green; equals `make lint`) |

> **Critical marker note:** Both subprocess stdio tests are `@pytest.mark.slow`
> (`test_mcp_stdio_smoke.py:7`, `test_mcp_jsonrpc_e2e.py:227`) and are **deselected by the default
> `-m 'not slow'`**. They must be invoked with `-m ""` (or `-m slow`) or they will silently not run.
> `[VERIFIED: viewed markers]`

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QBL-LOG-01 | Inventory is fresh & bucketed | lint/audit | `uv run ruff check src --select T20 --config 'lint.per-file-ignores={}'` (expect only `src/benchmarks/**` after fixes) | ✅ |
| QBL-LOG-02 | Non-CLI prints converted; no regressions | unit/integration | `uv run pytest tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_mcp_tool_handlers.py -q` + `uv run ruff check src` | ✅ |
| QBL-LOG-02 | Import progress still reaches user (on stderr) | integration | `uv run pytest tests/gateway/test_cli*.py -k import -q` (assert progress on `capsys.readouterr().err`, NOT `.out`) | ⚠️ Wave 0 (assertion likely missing) |
| QBL-LOG-03 | CLI/benchmark boundary holds; `cli/app.py` clean | lint | `uv run ruff check src/atelier/gateway/cli/app.py --select T20` → 0 | ✅ |
| QBL-LOG-04 | **No non-protocol stdout leak from MCP server** | smoke (slow) | `uv run pytest tests/gateway/test_mcp_stdio_smoke.py -m "" -q` **after hardening** | ⚠️ Wave 0 (test is lenient today) |

### Sampling Rate
- **Per task commit:** `uv run ruff check src` + `uv run pytest tests/gateway/test_p0_mcp_surfaces.py -q`
- **Per wave merge:** `uv run pytest tests/gateway/ -m "" -q` (includes slow stdio smoke + e2e)
- **Phase gate:** `make lint` green, `make typecheck` green, MCP stdio framing test green with the
  new strict stdout-purity assertion, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] **Harden `tests/gateway/test_mcp_stdio_smoke.py`** — today it parses stdout with
  `try: json.loads(line) except Exception: pass` (lines 78–83), so a stray banner is **silently
  swallowed and the test still passes**. Add a strict assertion: every non-empty stdout line MUST
  `json.loads` to a `dict` (no try/except swallow), proving QBL-LOG-04. (Note: `test_mcp_jsonrpc_e2e.py:306`
  already does strict `json.loads` per line — a stray print would fail it; mirror that rigor in the smoke test.)
- [ ] **CLI import stderr assertion** — add/confirm a test that runs an import and asserts progress
  lines appear on `stderr` and stdout contains no `[atelier]` progress. (Verifies the stderr-handler
  conversion didn't regress visibility.)
- [ ] No framework install needed (pytest/ruff/mypy already present).

*If the team prefers a dedicated regression: a new `test_no_stray_stdout_in_non_cli` that spawns
`atelier-mcp` with `--version` and a minimal init and asserts stdout is exclusively JSON-RPC
frames (the `--version` path writes one line then exits — handle that case explicitly).*

## Runtime State Inventory

This is a code-refactor phase (print → logger). Most runtime-state categories are N/A, but logging
**destination** is the relevant axis:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore keys reference print/stdout. `[VERIFIED]` | none |
| Live service config | MCP logger already file-routed: `_setup_file_logging` writes `atelier.mcp` → `~/.atelier/mcp/mcp.log` (NOT stdout). Converted `mcp_server` diagnostics should use this existing `_log`, not a new stream. `[VERIFIED: viewed]` | reuse existing file logger |
| OS-registered state | None | none |
| Secrets/env vars | `ATELIER_DEV_MODE=1` flips MCP tool visibility (used by stdio smoke test env). Not renamed; no secret in scope. **Log-hygiene risk:** converted log lines must not newly emit tokens/paths that prints previously kept off persistent logs. | review converted messages for secret leakage |
| Build artifacts | None — pure source edits; no package rename | none |

**Canonical question — "after all files updated, what still emits to stdout in a server context?"**
Answer after fixes: only legitimate JSON-RPC frames from the MCP server, `click.echo` from the CLI,
and benchmark dev-CLI reports (which never run inside the MCP process). Verified by the hardened
stdio framing test.

## Common Pitfalls

### Pitfall 1: Converting CLI progress to `logger.info()` makes it vanish
**What goes wrong:** Session-parser progress (`[atelier] importing i/total`) disappears for users
because the CLI configures **no** logging handler (root defaults to WARNING, no stderr stream).
**Why:** `cli/app.py` has only `logger = getLogger(__name__)`, no `basicConfig`/`StreamHandler`.
**How to avoid:** Pair every progress-print→logger conversion with an explicit INFO-level stderr
`StreamHandler` attached in the CLI `import` command path. Add a test asserting progress on `.err`.
**Warning signs:** `atelier import` runs silently; tests that previously checked `capsys.out` for
`[atelier]` now find nothing anywhere.

### Pitfall 2: Trusting the lenient smoke test as proof of clean stdout
**What goes wrong:** A stray banner ships because `test_mcp_stdio_smoke.py` swallows non-JSON lines
(`except Exception: pass`) and still passes.
**How to avoid:** Add a strict per-line `json.loads → dict` assertion before relying on it for
QBL-LOG-04. Mirror `test_mcp_jsonrpc_e2e.py:306`.
**Warning signs:** Test green but `atelier-mcp` prints a banner when run by hand.

### Pitfall 3: Touching the `mcp_server.py --version` print carelessly
**What goes wrong:** Replacing the `--version` print with a logger call sends version info to the
file log instead of the terminal, breaking `atelier-mcp --version` UX; or removing the early
`return` causes the version string to land mid-protocol.
**How to avoid:** Keep it as a direct `sys.stdout.write(...)`/`print` that executes only on the
`--version`/`-V` branch and returns before the stdio loop. It is user-facing CLI output, not a
server diagnostic.

### Pitfall 4: Running the framing tests on the default marker filter
**What goes wrong:** `uv run pytest tests/gateway/test_mcp_stdio_smoke.py` reports "no tests
collected (1 deselected)" because the test is `@pytest.mark.slow`. The phase looks validated but
nothing ran.
**How to avoid:** Always add `-m ""` for the stdio/e2e subprocess tests.

### Pitfall 5: Mistaking the docstring/`grep` count (132/35) for real work
**What goes wrong:** Planning 132 sites or 35 files inflates scope ~4x and risks editing docstrings
or `_fingerprint` substrings.
**How to avoid:** Trust the AST/ruff count (97 calls / 19 files). Use
`ruff --select T20 --config 'lint.per-file-ignores={}'` as the single source of truth.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Routing diagnostics off stdout | Custom stream-redirect wrapper around the MCP loop | Module `logging` + existing `_setup_file_logging` file handler | Already implemented and file-routed for `atelier.mcp` |
| User-visible CLI progress | `print(..., file=sys.stderr)` (still trips T201) | `logger.info` + CLI stderr `StreamHandler`, or `click.echo(..., err=True)` | Clears T201 *and* stays on stderr; click err-stream is the project idiom (9 `err=True` sites exist) |
| Detecting stray stdout | A bespoke byte-sniffer | Strict per-line `json.loads` assertion in the subprocess test | The e2e test already proves this pattern works |

**Key insight:** The infrastructure (file logger, click err-stream, subprocess framing tests)
already exists. Phase 24 is wiring existing primitives, not building new ones.

## Security Domain

This phase is logging hygiene, not a new attack surface, but two log-specific concerns apply:

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V7 Error Handling & Logging | yes | Don't log secrets/tokens; reuse the existing redaction helper (`core/foundation/redaction.redact`, already imported in `_common.py`) when converting prints that include session content |
| V5 Input Validation | partial | MCP server must reject/ignore non-JSON-RPC on stdout — the hardened framing test enforces this |

| Threat | STRIDE | Mitigation |
|--------|--------|------------|
| Secret leakage into persistent `mcp.log` via new `logger.debug` lines | Information Disclosure | Review converted messages; apply `redact()` where session payloads are interpolated |
| stdout framing corruption (stray bytes break JSON-RPC) | Tampering / DoS of integration | Strict per-line JSON assertion in stdio smoke test; benchmark CLIs kept out of MCP process |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Session-parser prints are reachable only via `cli/app.py import_all` (never MCP) | Inventory | If a future/hidden MCP tool calls an importer, those `logger.info`→stderr conversions are even more important; stdout still safe either way (low risk) |
| A2 | Benchmark dev-CLIs (`src/benchmarks/**`) are never imported by the MCP server | Classification | If a benchmark module is imported at MCP startup, its module-level prints (none found at import time — all inside `main()`/functions) could leak; verified prints are inside functions, not module scope |
| A3 | Keeping `src/benchmarks/**` T201-ignored satisfies QBL-LOG-03's "intended boundary" | Ignore plan | If reviewers expect benchmarks converted too, scope grows; brief explicitly scopes "non-CLI modules… gateway/server/background", benchmarks are dev CLIs |
| A4 | `mcp_server.py:5456` truly returns before the stdio loop on `--version` | Fix table | Verified by reading `main()` — the `--version` branch `return`s immediately (low risk) |

## Open Questions (RESOLVED)

1. **Should benchmark prints be migrated to `click.echo` or left as `print` under an ignore?**
   - Known: They never reach MCP; stdout is their intended channel.
   - RESOLVED: Leave as `print` with retained/globbed T201 ignore (minimal diff, Phase 25
     may revisit CLI/tooling output uniformly).

2. **Per-file vs `src/benchmarks/**` glob ignore?**
   - RESOLVED: Use the glob form if it is accepted by Ruff; it is cleaner and documents intent. If
     Ruff rejects the glob, keep the seven per-file ignores. In either case, add a comment
     and re-verifies `ruff check src` green.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | all commands | ✓ | (project standard) | none |
| `ruff` | T20 gate | ✓ | 0.15.14 | none |
| `pytest` | validation | ✓ | 9.0.3 | none |
| `mypy` | type gate | ✓ | strict | none |
| `atelier-mcp` entry point | stdio smoke | ✓ | `[project.scripts]` | none |

No missing dependencies. No external services needed (stdio tests spawn `uv run atelier-mcp`).

## Known Baseline (NOT Phase 24 work — do not fix)

Per Phase 23 VERIFICATION and the dirty worktree (184 changed/deleted paths):
- `make typecheck` fails on pre-existing WIP at `mcp_server.py:1074` (redundant cast) — unrelated.
- `make format-check` fails on unrelated dirty files (autopilot, SCIP registry test, context_reuse).
- 4 order-dependent flaky failures in `test_mcp_tool_handlers.py` from module-singleton state
  leakage — reproduce on clean HEAD; documented test-isolation defect, not a print site.
- `make test-full` cannot complete locally (serial hang ~14%; xdist tree-sitter
  `pyo3_runtime.PanicException` — parser unsendable across threads). Use targeted `uv run pytest`
  invocations for Phase 24 validation, not the full suite locally.

`uv run ruff check src` **is green today** (ignores intact) — this is the gate Phase 24 must keep
green while shrinking the ignore list. `[VERIFIED]`

## Sources

### Primary (HIGH confidence)
- Working tree AST walk (`ast.Call` / `func.id == "print"`) — 97 calls / 19 files
- `uv run ruff check src --select T20 --config 'lint.per-file-ignores={}'` — 97 / 19 (matches AST)
- Direct source reads: `mcp_server.py` (`main`, `_setup_file_logging`), `registry.py`,
  `session_parsers/{claude,_common,copilot}.py`, `publisher.py`, `insights.py`, `session_report.py`
- `tests/gateway/test_mcp_stdio_smoke.py`, `test_mcp_jsonrpc_e2e.py` (markers + parse strictness)
- `pyproject.toml` (`[tool.ruff.lint]`, `per-file-ignores`, pytest config), `Makefile`
- `.planning/REQUIREMENTS.md` (QBL-LOG-01–04 verbatim), Phase 22/23 SUMMARY/VERIFICATION
- `docs/plans/quality-and-benchmark-lift/M3-stdout-to-logging.md` (design intent)

### Secondary
- `CLAUDE.md` / `AGENTS.md` (uv-run mandate, layer architecture, tool substitution)

## Metadata

**Confidence breakdown:**
- Inventory & counts: HIGH — two independent methods (AST + ruff) agree exactly at 97/19.
- Classification (MCP-reachability): HIGH — call-graph verified via grep; `import_all` CLI-only.
- Ignore shrink plan: HIGH — 1:1 mapping confirmed against live `per-file-ignores`.
- CLI progress-visibility risk: HIGH — verified no `basicConfig`/handler in `cli/app.py`.
- Benchmark boundary recommendation: MEDIUM — depends on team preference (Open Question 1).

**Research date:** 2026-05-29
**Valid until:** ~2026-06-28 (stable; re-derive the T20 list if the worktree changes before planning)
