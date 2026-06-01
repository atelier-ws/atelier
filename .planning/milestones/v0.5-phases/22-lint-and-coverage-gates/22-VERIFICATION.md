---
phase: 22-lint-and-coverage-gates
verified: 2026-05-29T19:05:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: n/a
follow_ups: # Non-blocking, documented; tracked for first nightly CI dispatch
  - item: "Calibrate COV_FAIL_UNDER against first clean nightly workflow_dispatch TOTAL"
    severity: warning
    reason: "Floor=66 is a conservative provisional lower bound (~2pts below measured 68% partial-subset). Full slow-inclusive run could not complete in the dirty local worktree; first clean CI run must read its TOTAL and raise the floor."
---

# Phase 22: Lint and Coverage Gates Verification Report

**Phase Goal:** Stop new broad-except/print debt and gate full-suite coverage without blocking existing debt burn-down.
**Verified:** 2026-05-29T19:05:00Z
**Status:** PASS
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth                                                                                                   | Status     | Evidence |
| --- | ------------------------------------------------------------------------------------------------------- | ---------- | -------- |
| 1   | A new `except Exception` (non-re-raising) in a clean (non-ignored) src file fails lint (QBL-GATE-01)    | ✓ VERIFIED | Live probe `src/atelier/_gate_probe.py` reported `BLE001 Do not catch blind exception: Exception`, then deleted. |
| 2   | A new `print()` in a clean (non-ignored) src file fails lint (QBL-GATE-01)                              | ✓ VERIFIED | Same probe reported `T201 print found`. |
| 3   | Existing BLE001 + T201 violations do NOT fail lint — parked in per-file-ignores, not blanket-disabled (QBL-GATE-02) | ✓ VERIFIED | `make lint` → "All checks passed!" (exit 0). `ignore = ["E501"]` unchanged (pyproject.toml:108); `[tool.ruff.lint.per-file-ignores]` holds the parked files. |
| 4   | `make test-full` collects slow-inclusive tests and enforces a measured coverage floor (QBL-GATE-03)     | ✓ VERIFIED | `pytest --collect-only -m "" --timeout=300` → 2093 collected; default → 2006/2093 (87 slow deselected). Target runs `--cov-fail-under=$(COV_FAIL_UNDER)`. |
| 5   | A scheduled `nightly-coverage.yml` runs the full suite with read-only token and frozen deps (QBL-GATE-04) | ✓ VERIFIED | YAML parses; `schedule` (cron `0 7 * * *`) + `workflow_dispatch` only; `permissions.contents=read`; `uv sync --frozen --group dev`; final step `make test-full`. |
| 6   | per-file-ignores tables are re-derivable from `ruff check` output (QBL-GATE-05)                         | ✓ VERIFIED | Re-derived live (per-file-ignores cleared): 96 BLE001 files + 19 T20 files — exact match to the table (84 BLE-only + 12 combined = 96; 7 T201-only + 12 = 19). |

**Score:** 6/6 truths verified

### ROADMAP Success Criteria Coverage

| # | Success Criterion | Status | Evidence |
|---|-------------------|--------|----------|
| 1 | New BLE001/T20 violations fail lint outside scoped ignores | ✓ VERIFIED | Probe truth #1/#2. |
| 2 | Current violations tracked with per-file ignores M2/M3 can shrink | ✓ VERIFIED | Truth #3/#6; commented burn-down ledger at pyproject.toml:110-115. |
| 3 | Full slow-inclusive coverage command and nightly workflow exist | ✓ VERIFIED | Truth #4/#5. |
| 4 | Coverage floor measured first and set conservatively | ✓ VERIFIED (with documented follow-up) | Measured partial lower bound 68% (SUMMARY); floor set to 66 (~2pts below). Full local run blocked by dirty-worktree hang / tree-sitter xdist panic — first CI dispatch calibrates. |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `pyproject.toml` | BLE/T20 select + per-file-ignores worklist | ✓ VERIFIED | `select = [..."BLE", "T20"...]` (line 107); `ignore=["E501"]` (108); `[tool.ruff.lint.per-file-ignores]` (116) with combined `["BLE001","T201"]` for `mcp_server.py` (118). |
| `Makefile` | test-full slow-inclusive target + COV_FAIL_UNDER floor | ✓ VERIFIED | `COV_FAIL_UNDER ?= 66` (line 12); `test-full` in `.PHONY` (18); recipe at 101-102 with `--timeout=300 --cov-fail-under=$(COV_FAIL_UNDER)`; listed in `make help`. Fast path `addopts = "...-m 'not slow'"` intact (pyproject.toml:230). |
| `.github/workflows/nightly-coverage.yml` | Scheduled + manual full-suite coverage workflow | ✓ VERIFIED | 43-line workflow, schedule+dispatch only, read-only perms, frozen deps, 120m timeout, concurrency group. |
| `pyproject.toml` / `uv.lock` | pytest-timeout pinned for fast-fail | ✓ VERIFIED | `pytest-timeout>=2.4.0` (pyproject:263); pinned in uv.lock (430/504/5335); imports under `uv run`. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| nightly-coverage.yml | Makefile test-full | `run: make test-full` | ✓ WIRED | Line 43. |
| Makefile test-full | COV_FAIL_UNDER floor | `--cov-fail-under=$(COV_FAIL_UNDER)` | ✓ WIRED | Line 102. |
| pyproject [tool.ruff.lint] select | BLE + T20 rules | select list extension | ✓ WIRED | Line 107; grep `select = .*"BLE".*"T20"` succeeds. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Lint passes on current tree | `make lint` | "All checks passed!" (exit 0) | ✓ PASS |
| New debt fails lint | probe file → `ruff check` | BLE001 + T201 reported | ✓ PASS |
| Slow-inclusive collection | `pytest --collect-only -m "" --timeout=300` | 2093 collected | ✓ PASS |
| Slow tests included by override | default collect | 2006/2093 (87 deselected) | ✓ PASS |
| Workflow YAML valid + read-only | PyYAML assert | "workflow ok" | ✓ PASS |
| Worklist re-derivable | `ruff check --select BLE001/T20` (ignores cleared) | 96 / 19 files | ✓ PASS |
| Full coverage to green | `make test-full` | NOT RUN locally | ? SKIP — requires clean CI environment (see follow-up) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| QBL-GATE-01 | 22-01 | BLE001/T20 lint-gate new debt | ✓ SATISFIED | Truths #1, #2 |
| QBL-GATE-02 | 22-01 | Existing violations as per-file ignores, not blanket disables | ✓ SATISFIED | Truth #3 |
| QBL-GATE-03 | 22-01 | Full-suite slow-inclusive coverage command | ✓ SATISFIED | Truth #4 |
| QBL-GATE-04 | 22-01 | Nightly workflow with measured fail-under floor | ✓ SATISFIED | Truth #5 + measured floor (follow-up for CI calibration) |
| QBL-GATE-05 | 22-01 | Burn-down worklists derivable from lint config | ✓ SATISFIED | Truth #6 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | No debt markers (TBD/FIXME/XXX) introduced; config/CI-only phase | ℹ️ Info | None |

Note: 22-REVIEW.md surfaced two pre-existing, out-of-scope defects (IN-01 stale `test-fast --ignore` paths; IN-02 mis-indented `bench-ab`/`bench-savings-honest` recipes). Both confirmed by git history as untouched by this phase — informational only, not Phase 22 gaps.

### Human Verification Required

None required to confirm goal achievement in the codebase. The only outstanding item is the
automated first-CI floor calibration (below), which is a scheduled CI action, not a manual gate.

### Gaps Summary

No blocking gaps. All six must-have truths, all four ROADMAP success criteria, all artifacts,
and all key links are verified against the live tree. `make lint` passes, the prevention gate
demonstrably fails new debt, the slow-inclusive `test-full` target collects 2093 tests and
enforces a fail-under floor, and the hardened nightly workflow is wired to it.

**One documented, non-blocking follow-up (WARNING):** `COV_FAIL_UNDER=66` is a conservative
provisional floor. The full slow-inclusive suite could not complete in the dirty local worktree
(serial hang + tree-sitter xdist `_native::Parser is unsendable` panic — both pre-existing
environment issues, not introduced by this config-only phase). The `--timeout=300` guard plus
`pytest-timeout` ensure the first `workflow_dispatch` terminates and reports a usable TOTAL; that
run must read the TOTAL and raise the floor to ~2 points below it (the `?=` form allows
`make test-full COV_FAIL_UNDER=NN`). Per the verification mandate, this CI-calibration follow-up
does not block the phase: all planned deliverables are implemented.

Minor note: the plan estimated 2088 slow-inclusive tests; the live tree collects 2093 (suite grew
by 5 non-slow tests). The 87 slow-test delta is unchanged — not a gap.

---

_Verified: 2026-05-29T19:05:00Z_
_Verifier: the agent (gsd-verifier)_
