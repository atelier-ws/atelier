---
phase: 1
slug: retrieval-core-routed-symbol-search
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-18
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + existing repo make targets |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/core/test_code_context.py tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_savings_api.py -q` |
| **Full suite command** | `make lint && make typecheck && make test` |
| **Estimated runtime** | ~30-300 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/core/test_code_context.py tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_savings_api.py -q`
- **After every plan wave:** Run `make lint && make typecheck && make test`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01-01 | 1 | FNDN-01 | — | Cache, provenance, and token metadata stay on the existing `code` response shape | unit + gateway | `uv run pytest tests/core/test_code_context.py tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_savings_api.py -q` | ✅ | ⬜ pending |
| 01-02-01 | 01-02 | 2 | FNDN-02 | — | Routed SCIP backend preserves fallback behavior and does not add new top-level MCP tools | unit + gateway | `uv run pytest tests/core/test_code_context.py tests/gateway/test_mcp_tool_handlers.py -q` | ✅ | ⬜ pending |
| 01-03-01 | 01-03 | 3 | NAVG-01 | — | Hardened `code op="search"` adds snippet/ranking behavior without breaking existing MCP contracts | gateway | `uv run pytest tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_savings_api.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/benchmarks/code_intel/` — add the benchmark harness expected by the active code-intel docs so Phase 1 can produce required cost evidence
- [ ] `tests/core/test_code_context.py` — extend fixtures/coverage for cache invalidation, stable metadata, and SCIP routing
- [ ] `tests/gateway/test_p0_mcp_surfaces.py` and `tests/gateway/test_mcp_tool_handlers.py` — add/refresh coverage for hardened `tool_code` response fields and unchanged MCP surface

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Validate brownfield-safe coexistence with the user's in-flight `code_context` and MCP edits | FNDN-01, FNDN-02, NAVG-01 | Existing worktree changes increase merge/overwrite risk that automated tests do not fully express | Review the diff for `src/atelier/core/capabilities/code_context/` and `src/atelier/gateway/adapters/mcp_server.py` before phase completion; confirm planned tasks only narrow/complete current edits rather than replacing them wholesale. |
| Confirm SCIP bootstrap assumptions match available local toolchains | FNDN-02 | Local environment lacks `go`, so initial Phase 1 indexer support must stay within realistic Python/TypeScript paths | Validate the planned indexer/bootstrap steps against actual available binaries before execution; if a toolchain is unavailable, the plan must document the fallback or narrow the scope. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
