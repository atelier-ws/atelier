---
phase: 16
slug: canonical-language-registry
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-29
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest via `uv run pytest` |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/infra/code_intel/test_languages.py tests/core/test_code_context.py -q` |
| **Full suite command** | `make lint && make typecheck && make test` |
| **Estimated runtime** | ~120 seconds focused; full gate varies |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/infra/code_intel/test_languages.py tests/core/test_code_context.py -q`
- **After every plan wave:** Run `make lint && make typecheck && uv run pytest tests/core/test_code_context.py tests/infra -q`
- **Before `/gsd-verify-work`:** `make lint && make typecheck && make test` must pass
- **Max feedback latency:** 180 seconds for focused checks

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | DLS-LANG-01 | — | N/A | unit | `uv run pytest tests/infra/code_intel/test_languages.py -x` | No - Wave 0 | pending |
| 16-01-02 | 01 | 1 | DLS-LANG-02 | — | N/A | unit | `uv run pytest tests/infra/code_intel/test_languages.py -k extensions -x` | No - Wave 0 | pending |
| 16-02-01 | 02 | 2 | DLS-LANG-03 | — | N/A | regression | `uv run pytest tests/core/test_shell_outline.py -k shell -x` | Partial - Wave 0 | pending |
| 16-02-02 | 02 | 2 | DLS-LANG-04 | — | N/A | unit | `uv run pytest tests/infra/code_intel/test_languages.py -k canonical tests/infra/code_intel/scip/test_scip_adapter.py -x` | Partial - Wave 0 | pending |

*Status: pending, green, red, flaky*

---

## Wave 0 Requirements

- [ ] `tests/infra/code_intel/test_languages.py` — registry unit tests for `Language`, `language_for_path`, `language_by_name`, `EXTENSION_TO_LANGUAGE`, and `ALL_LANGUAGES`
- [ ] `tests/infra/code_intel/test_languages.py` — legacy extension coverage and unknown-path fallback tests for DLS-LANG-02
- [ ] `tests/core/test_shell_outline.py` or `tests/core/test_code_context.py` — shell fixture regression proving `.sh` resolves to `bash` and produces a `kind: "treesitter"` outline
- [ ] Confirm `tests/infra/code_intel/` package path supports the new test module

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | — | All phase behaviors have automated verification | — |

---

## Validation Sign-Off

- [x] All tasks have automated verify commands or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency target recorded
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-29
