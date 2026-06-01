---
phase: 22-lint-and-coverage-gates
reviewed: 2026-05-29T18:20:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - pyproject.toml
  - uv.lock
  - Makefile
  - .github/workflows/nightly-coverage.yml
  - .github/workflows/tests.yml
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 22: Code Review Report (final re-review after timeout guard)

**Reviewed:** 2026-05-29T18:20:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found (no blockers; one non-blocking warning, two info items)

## Summary

Config/CI-only phase: Ruff `BLE`/`T20` enabled with a scoped
`[tool.ruff.lint.per-file-ignores]` burn-down ledger, a slow-inclusive `make test-full`
coverage target with a `COV_FAIL_UNDER` floor and a `--timeout=300` fast-fail guard, and a
scheduled `nightly-coverage.yml` workflow.

This re-review re-verifies the prior findings against the current working tree after the
timeout guard was added. **The prior fast-fail blocker (WR-01) is now RESOLVED.** No
blockers remain.

**Verified as correct against the live tree:**

- **Timeout guard present and functional.** `Makefile:102` now runs
  `uv run pytest -m "" --timeout=300 --cov=atelier --cov-report=term-missing --cov-fail-under=$(COV_FAIL_UNDER)`.
  A hung test now fails in 5 minutes instead of burning the full 120-minute budget.
- **`pytest-timeout` is resolvable in CI.** `pytest-timeout>=2.4.0` is listed in
  `[dependency-groups].dev` (`pyproject.toml:263`) and pinned to `2.4.0` in `uv.lock`. The
  nightly workflow installs via `uv sync --frozen --group dev`, which reads
  `[dependency-groups].dev` (not `[project.optional-dependencies].dev`), so the plugin loads.
  Confirmed: `uv run pytest --version` shows `pytest-timeout-2.4.0`.
- **Slow-inclusive collection works.** `uv run pytest --collect-only -q -m "" --timeout=300`
  collects **2093** tests; the default filter (`addopts = -m 'not slow'`) collects 2006
  (87 slow deselected). `-m ""` overrides the marker filter as designed.
- **`test-full` runs serially (no `-n auto`).** This sidesteps the tree-sitter
  `_native::Parser is unsendable` xdist panic documented in the SUMMARY, so the
  parallelism hazard does not apply to the nightly path.
- **Ruff gate is correct.** `select` includes `"BLE"` and `"T20"`; top-level `ignore` stays
  `["E501"]`; all existing debt is parked via exact-path `per-file-ignores`. `make lint`
  passes, and new debt in a clean file still fails (verified-evidence + probe in SUMMARY).
- **Nightly workflow hardened.** `permissions: contents: read`, `concurrency.group:
  nightly-coverage` + `cancel-in-progress: false`, `timeout-minutes: 120`,
  `schedule` (`0 7 * * *`, distinct from docs-governance `25 3 * * *`) + `workflow_dispatch`
  only (no `pull_request`/`push`), `uv sync --frozen --group dev`, single `make test-full` step.
  YAML parses.

## Prior findings — disposition

- **WR-01 (no fast-fail guard / unvalidated gate): RESOLVED.** The `--timeout=300` flag plus
  `pytest-timeout` now bound any single hanging test to 5 minutes, eliminating the
  "burn the whole 120m budget" risk. The remaining un-run-on-CI concern collapses to floor
  calibration, captured below as WR-01 (re-scoped, non-blocking).
- **WR-02 / floor (COV_FAIL_UNDER=66 provisional): STILL OPEN, non-blocking** — carried forward.
- **IN-01 (stale `test-fast` ignore paths): STILL OPEN** — carried forward.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `COV_FAIL_UNDER=66` is a provisional floor pending first-CI calibration

**File:** `Makefile:7-12`, `Makefile:102`

**Issue:** The floor `66` was derived from a partial-subset lower bound (68%) because the full
slow-inclusive suite never completed locally (documented in `22-01-SUMMARY.md`). Until the
first `workflow_dispatch` run reports an actual TOTAL, the gate is (a) potentially too loose —
real coverage could regress several points before firing — and (b) could in principle false-fail
if clean CI exercises fewer modules than the dirty local worktree. Calibration is tracked only
by an inline comment and a SUMMARY note, with no separate tracking task.

**Classification:** Non-blocking. The first nightly `workflow_dispatch` has not yet run, so this
is expected CI calibration, not a defect in the shipped config. The timeout guard ensures the
first run terminates and reports a usable TOTAL.

**Fix:** After the first green `workflow_dispatch` on clean `main`, read the reported TOTAL and
set `COV_FAIL_UNDER` to ~2 points below it (the `?=` form already allows
`make test-full COV_FAIL_UNDER=NN` override). File an explicit follow-up so the provisional
floor is not silently forgotten.

## Info

### IN-01: `make test-fast` ignores non-existent test paths (silent no-ops)

**File:** `Makefile:96` (pre-existing; not modified in this phase)

**Issue:** `test-fast` passes `--ignore=tests/test_postgres_store.py
--ignore=tests/test_worker_jobs.py`, but neither path exists in the tracked tree. pytest treats
`--ignore` of a missing path as a silent no-op, so these flags exclude nothing. Harmless to
`test-fast` today, but the repo's record of "which tests need services" is stale, which is also
relevant to predicting whether the nightly full suite will hit unavailable-service failures.

**Fix:** Remove the dead `--ignore` flags, or repoint them at real paths and convert
service-dependent tests to skip-on-missing-service (e.g. a `DATABASE_URL` skip marker /
`pytest.importorskip`) so the exclusion is meaningful. Out of phase-22 scope.

### IN-02: Two benchmark Makefile targets are silently broken (pre-existing, out of phase-22 scope)

**File:** `Makefile:146-151`

**Issue:** Lines 142-151 are indented with a leading tab, so GNU Make attaches them to the
`benchmark` recipe instead of declaring new rules. Confirmed live:
- `make bench-ab` → `*** No rule to make target 'bench-ab'. Stop.` (the target does not exist)
- `make bench-savings-honest` → `Nothing to be done` (recognized only because it is in `.PHONY`,
  but its recipe lines were swallowed into `benchmark`'s recipe).
`benchmark`, `proof-cost-quality`, and the phase-22 `test-full` target are unaffected (correct
column-0 declarations). The git history confirms these lines were **not** touched by the phase-22
commit — this is a pre-existing defect surfaced incidentally while reviewing the file.

**Classification:** Pre-existing and unrelated to the lint/coverage gates; reported for awareness,
not as a phase-22 blocker.

**Fix:** Remove the leading tabs from lines 142-151 so `bench-ab:` and `bench-savings-honest:`
are parsed as top-level rules (their recipe lines stay tab-indented). Also add `bench-ab` to
`.PHONY` (currently only `bench-savings`, which no longer exists, is listed).

---

_Reviewed: 2026-05-29T18:20:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard (final re-review after timeout guard)_
