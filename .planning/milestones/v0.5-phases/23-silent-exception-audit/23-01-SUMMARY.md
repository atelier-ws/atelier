---
phase: 23-silent-exception-audit
plan: 01
subsystem: gateway
tags: [logging, exception-handling, mcp, cli, observability, ruff-ble001]

# Dependency graph
requires:
  - phase: 22-lint-and-coverage-gates
    provides: BLE001/T20 ruff gates with per-file ignores that this phase burns down
provides:
  - 9 mcp_server.py in-scope silent except handlers made observable (4 narrowed, 5 best-effort logged)
  - 4 cli/app.py in-scope silent except handlers made observable (1 narrowed, 3 best-effort logged)
  - Fresh tree-wide silent-pass enumeration baseline (before/after) recorded
affects: [23-02, 23-03, 24-stdout-to-logging]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Best-effort handler observability: keep broad suppression, replace silent `pass` with `_log/logger.debug(<what failed>, exc_info=True)` + `# why best-effort` comment"
    - "Narrow-and-log: replace `except Exception:` with realistic tuple ((OSError,), (OSError, json.JSONDecodeError), (OSError, subprocess.SubprocessError)) + debug log"
    - "Never print() in mcp_server.py — stdout is the MCP JSON-RPC framing channel; all observability via stderr loggers"

key-files:
  created: []
  modified:
    - src/atelier/gateway/adapters/mcp_server.py
    - src/atelier/gateway/cli/app.py

key-decisions:
  - "Reused existing loggers (_log/logger) — no new logger added per RESEARCH census"
  - "Preserved fail-open/best-effort semantics on every site; never re-raise (Pitfall 3)"
  - "Logged at debug (not warning) for best-effort side-effects per RESEARCH recommendation"
  - "Staged only Phase 23 hunks via filtered `git apply --cached`; pre-existing WIP in both files left unstaged and intact"
  - "mcp_server.py keeps BLE001+T201 and cli/app.py keeps BLE001 per-file ignores — other broad/print handlers remain (QBL-EXC-03 handled in plans 02/03)"

patterns-established:
  - "Hunk-level staging in dirty worktrees: build a filtered patch (accept-list of old-start line numbers) and `git apply --cached` to commit only in-scope hunks without touching unrelated WIP"

requirements-completed: [QBL-EXC-01, QBL-EXC-02, QBL-EXC-04]

# Metrics
duration: ~45min
completed: 2026-05-29
---

# Phase 23 Plan 01: Gateway MCP/CLI Silent Exception Audit Summary

**Made the 13 highest-risk gateway silent `except Exception: pass` handlers (9 in MCP stdio adapter, 4 in CLI) observable via stderr debug logs with `exc_info=True` — 4 narrowed to realistic exception tuples, 9 kept best-effort-with-logging — without breaking JSON-RPC framing or fail-open semantics.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 2/2
- **Files modified:** 2 (in-scope hunks only)

## Accomplishments

- mcp_server.py: 9 in-scope silent handlers made observable.
  - Narrowed (4): site 634 `_register_mcp_session` → `(OSError,)`; sites 665/690/712 (session-id / model / sidecar-session reads) → `(OSError, json.JSONDecodeError)`; site 5441 `main` git rev-parse → `(OSError, _subprocess.SubprocessError)`.
  - Best-effort logged (5): sites 770/795 `_append_savings` (statusline sidecar + per-session ledger), 1183 `tool_get_context` (prefix-cache planning), 1469 `tool_route` (model recommendation) — all keep broad `except Exception:` + `_log.debug(..., exc_info=True)` + `# why best-effort` comment.
- cli/app.py: 4 in-scope silent handlers made observable.
  - Narrowed (1): site 1215 `_detect_git_root` → `(OSError, _subprocess.SubprocessError)`.
  - Best-effort logged (3): sites 5931/5966/6052 in `_render_dashboard_impl` (cost aggregation, SQLite trace read, run-JSON parse) — broad + `logger.debug(..., exc_info=True)` + comment.
- No `print()` introduced in mcp_server.py (count stayed at 1 pre-existing); MCP stdio framing preserved.
- All fail-open fallbacks (return / setdefault / continue-to-next) preserved; nothing re-raises.

## Task Commits

1. **Task 1 + Task 2 (combined source commit): observe gateway silent exceptions** - `0df47e4` (fix)

   _Both tasks edit the same two files; staged as one atomic source commit using a filtered `git apply --cached` patch limited to the 13 Phase-23 hunks. Pre-existing user/WIP hunks in both files (6 in mcp_server.py, 2 in cli/app.py) were deliberately left unstaged and untouched per the critical worktree constraint._

**Plan metadata:** committed separately with this SUMMARY + STATE/ROADMAP/REQUIREMENTS updates.

## Files Created/Modified

- `src/atelier/gateway/adapters/mcp_server.py` - 9 in-scope silent handlers narrowed-or-logged.
- `src/atelier/gateway/cli/app.py` - 4 in-scope silent handlers narrowed-or-logged.

## Fresh Enumeration (QBL-EXC-01)

Command: `grep -rn -A1 "except Exception" src --include='*.py' | grep -B1 "pass" | grep -c "except Exception"`

| Scope | Before | After | Δ |
|-------|-------:|------:|--:|
| Tree-wide silent `except Exception: pass` sites | 28 | 15 | −13 |
| mcp_server.py in-scope silent sites | 9 | 0 | −9 |
| cli/app.py in-scope silent sites | 4 | 0 | −4 |

Per-file observability counters:

| Metric | mcp_server.py | cli/app.py |
|--------|--------------:|-----------:|
| `exc_info=True` before | 6 | 4 |
| `exc_info=True` after | 15 (+9) | 8 (+4) |
| `print(` before/after | 1 / 1 (unchanged) | n/a |

The remaining 15 tree-wide silent sites are out of scope for plan 01 (other files / other plans 02–03).

## BLE001 / T201 Ignores (intentionally retained)

Per the RESEARCH census, **mcp_server.py keeps its `BLE001` + `T201`** per-file ignore and **cli/app.py keeps its `BLE001`** ignore — both files still contain other non-silent broad handlers (and mcp_server.py pre-existing print). `pyproject.toml` was NOT touched in this plan; ignore removal (QBL-EXC-03) is owned by plans 02/03. A log does not clear BLE001 — only narrowing does, which is why the 9 best-effort sites still trip BLE001 by design.

## Validations Run

- `uv run ruff check src/atelier/gateway/adapters/mcp_server.py src/atelier/gateway/cli/app.py` → **All checks passed!** (exit 0)
- `uv run black --check` (both files) → **2 files would be left unchanged** (formatting clean)
- `uv run pytest tests/gateway/test_p0_mcp_surfaces.py` → **35 passed** in 3.22s
- `uv run pytest tests/gateway/test_mcp_tool_handlers.py` → 53 passed, 3 skipped, **4 failed** (see Deferred Issues — pre-existing flakiness)
- `tests/gateway/test_mcp_stdio_smoke.py` is marked `slow` and deselected by the repo default `addopts = "-ra --strict-markers -m 'not slow'"`; collected cleanly (1 deselected).

## Deviations from Plan

**None to the source changes** — both tasks executed exactly as specified (narrow vs. best-effort-log assignments per RESEARCH classification).

Process note (worktree constraint compliance): because both target files carried unrelated pre-existing WIP, Tasks 1 and 2 were committed as a single atomic source commit (`0df47e4`) built from a filtered patch (`git apply --cached`) containing only the 13 Phase-23 hunks. This honors the "preserve unrelated user work / stage only Phase 23 hunks" constraint. No `git restore`/`reset --hard`/`clean`/`stash` was used.

## Deferred Issues (pre-existing, NOT caused by this plan)

`tests/gateway/test_mcp_tool_handlers.py` has **order-dependent / flaky failures** driven by module-level singleton state leakage (`_current_ledger`, `_realtime_ctx` — already a documented STATE.md Watch Point; these tests require subprocess isolation that the suite does not yet provide):

- `test_tools_list_returns_exact_consolidated_surface_in_dev_mode`
- `test_cli_tools_list_respects_stable_and_dev_modes`
- `test_context_reuses_bootstrap_blocks_instead_of_enqueuing_duplicate_work`
- `test_context_injects_preseeded_bootstrap_blocks_without_recomputing`

**Proof these are baseline blockers, not regressions:**
1. Each fails inside the full-file run but **passes in isolation** (e.g. `test_context_reuses_bootstrap_blocks...` → 1 passed when run alone).
2. Running the 4 as a group is **non-deterministic** (3 failed in the dirty worktree; 1 failed in a clean checkout).
3. A clean `git worktree` at `HEAD` (no WIP, none of this plan's changes) reproduces the same grouped failures — confirming they are independent of this diff.
4. None of this plan's edited code paths touch tool-list construction or bootstrap enqueue/dedup logic; the 13 changes only swap silent `pass` for narrowed/logged handlers.

These are out of scope for Phase 23 (they are a test-isolation defect, not a silent-exception site) and are logged here rather than fixed.

## Self-Check: PASSED

- FOUND: src/atelier/gateway/adapters/mcp_server.py
- FOUND: src/atelier/gateway/cli/app.py
- FOUND: .planning/phases/23-silent-exception-audit/23-01-SUMMARY.md
- FOUND commit: 0df47e4
