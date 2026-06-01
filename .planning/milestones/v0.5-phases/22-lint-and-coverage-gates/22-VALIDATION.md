---
phase: 22
slug: lint-and-coverage-gates
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-29
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-cov 7.1.0; Ruff 0.15.14 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `make lint` |
| **Full suite command** | `uv run pytest -m "" --cov=atelier --cov-report=term-missing --cov-fail-under=<measured floor>` |
| **Estimated runtime** | Full suite unknown until measured; lint/typecheck/fast tests use existing repo timings |

---

## Sampling Rate

- **After every task commit:** Run the task-specific lint/config command from the plan.
- **After every plan wave:** Run `make lint && make typecheck && make test`.
- **Before `/gsd-verify-work`:** Run the dry-run nightly command with the measured fail-under floor and parse the new workflow YAML.
- **Max feedback latency:** One task or wave; no three consecutive tasks without automated verification.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 22-01-01 | 01 | 1 | QBL-GATE-01, QBL-GATE-02, QBL-GATE-05 | T-22-01 | New blind-except/print debt fails outside scoped ignores | lint/config | `make lint` plus `uv run ruff check src --select BLE001,T20 --statistics` | ✅ | ⬜ pending |
| 22-01-02 | 01 | 1 | QBL-GATE-03 | T-22-02 | Full coverage target includes slow tests and applies a measured floor only on the full path | command | `make test-full` | Created in plan | ⬜ pending |
| 22-01-03 | 01 | 1 | QBL-GATE-04 | T-22-03 | Nightly workflow runs with read-only token and frozen dependencies | workflow | `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/nightly-coverage.yml'))"` | Created in plan | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## In-Plan Creation Requirements

- [ ] `Makefile` — Task 2 adds `test-full` target with slow-inclusive coverage and fail-under before running its command verification.
- [ ] `.github/workflows/nightly-coverage.yml` — Task 3 creates the scheduled + manual workflow before parsing it.
- [ ] `pyproject.toml` — Task 1 enables Ruff BLE/T20 and encodes existing violations as per-file ignores before lint verification.
- [ ] Measured coverage total — Task 2 sets nightly fail-under about two points below the measured full-suite result.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Coverage floor selection | QBL-GATE-04 | The floor depends on the observed full-suite coverage in the current checkout/CI environment | Run the full coverage command, record total coverage, and set the floor about two points below it. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or in-plan creation dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] In-plan creation covers all initially missing references
- [ ] No watch-mode flags
- [ ] Feedback latency stays bounded to task/wave commands
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
