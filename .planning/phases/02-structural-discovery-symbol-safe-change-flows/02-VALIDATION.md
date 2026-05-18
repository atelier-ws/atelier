---
phase: 2
slug: structural-discovery-symbol-safe-change-flows
status: pending
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-18
---

# Phase 2 - Validation Strategy

> Per-phase validation contract for structural discovery, symbol-safe edits, and usages navigation on existing MCP surfaces.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + existing repo make targets |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/core/test_code_context.py tests/core/test_rich_edit.py tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_mcp_jsonrpc_e2e.py tests/infra/code_intel/scip/test_scip_adapter.py tests/benchmarks/code_intel/test_symbol_search_bench.py -q` |
| **Full suite command** | `make lint && make typecheck && make test` |
| **Estimated runtime** | ~30-300 seconds |

---

## Sampling Rate

- **After every task commit:** run the smallest targeted pytest subset for the touched plan surface.
- **After every plan wave:** run the Phase 2 quick command plus any new benchmark slice added by that wave.
- **Before verification:** run `make lint && make typecheck && make test`, while tracking unrelated pre-existing failures separately if they remain outside the phase scope.
- **Max feedback latency:** 300 seconds.

---

## Per-Plan Verification Map

| Plan | Milestone | Requirement | Secure / correct behavior | Expected automated coverage |
|------|-----------|-------------|---------------------------|-----------------------------|
| `02-01` | M5 | `DISC-02` | `code op="pattern"` stays on the existing MCP surface, resolves the explicit `ast-grep` binary safely, and returns structural matches or rewrites without silently falling back to regex behavior | `tests/gateway/test_mcp_tool_handlers.py`, `tests/gateway/test_p0_mcp_surfaces.py`, new infra/benchmark coverage under `tests/benchmarks/code_intel/` |
| `02-02` | M12 | Phase-wide hardening (partial close only) | Cache, budget, payload defaults, and diagnostics stay additive and low-token across the shipped search/pattern flows, while Plans `02-03` and `02-04` keep ownership of symbol-edit and usages follow-through checks | `tests/core/test_code_context.py`, `tests/gateway/test_p0_mcp_surfaces.py`, `tests/gateway/test_mcp_tool_handlers.py`, `tests/benchmarks/code_intel/test_cost_discipline.py` |
| `02-03` | M4 | `DISC-01` | Symbol-safe edit descriptors resolve the intended symbol, reject ambiguous or stale targets clearly, and preserve existing edit/diff recording semantics | `tests/core/test_rich_edit.py`, `tests/gateway/test_mcp_jsonrpc_e2e.py`, plus targeted edit-path regressions |
| `02-04` | M3 | `NAVG-02` | `code op="usages"` returns grouped references on the existing `code` surface with routed backend support or explicit fallback behavior | `tests/core/test_code_context.py`, `tests/gateway/test_mcp_tool_handlers.py`, `tests/infra/code_intel/scip/test_scip_adapter.py`, usages-vs-grep benchmark coverage |

---

## Wave 0 Requirements

- [ ] Reuse the existing code-intel benchmark landing zone under `src/benchmarks/code_intel/` and `tests/benchmarks/code_intel/`.
- [ ] Keep Phase 1 suites green while Phase 2 extends the same surfaces:
  - `tests/core/test_code_context.py`
  - `tests/gateway/test_p0_mcp_surfaces.py`
  - `tests/gateway/test_mcp_tool_handlers.py`
  - `tests/infra/code_intel/scip/test_scip_adapter.py`
- [ ] Add/extend tests for symbol-safe edit behavior in:
  - `tests/core/test_rich_edit.py`
  - `tests/gateway/test_mcp_jsonrpc_e2e.py`
- [ ] Define benchmark assertions for:
  - structural pattern flow versus text-search/read/edit baseline
  - usages flow versus grep/read baseline
  - M12 payload/default-policy hardening

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Confirm `ast-grep` bootstrap and binary discovery are realistic on the developer machine | `DISC-02` | The current environment does not have `ast-grep`, and Linux `sg` is the wrong binary name here | Verify the chosen binary discovery/install story on the real machine before marking pattern search complete. |
| Review brownfield coexistence across `engine.py`, `mcp_server.py`, and `rich_edit.py` | `DISC-01`, `DISC-02`, `NAVG-02` | Automated tests prove behavior, not whether shared surfaces stayed narrow and maintainable | Review final diffs in the shared landing zones before phase completion. |
| Exercise a real symbol-first edit and usages workflow | `DISC-01`, `NAVG-02` | Benchmarks and regression suites do not prove operator UX | Run a practical agent flow that finds a symbol structurally, edits it by symbol, and inspects usages without falling back to line-number or ad hoc grep-first behavior. |

---

## Validation Sign-Off

- [x] Phase 2 reuses existing repo validation tooling
- [x] Feedback latency target remains under 300 seconds
- [x] Manual-only checks are explicitly recorded
- [ ] Wave 0 benchmark/test gaps closed
- [ ] Phase 2 traces and benchmark evidence captured
- [ ] Final approval recorded

## M12 Partial-Close Contract

- Plan `02-02` freezes cache keys, budget packing order, low-token defaults, and additive diagnostics for the currently shipped `code` flows.
- Plan `02-02` does **not** fully close M12. Plans `02-03` and `02-04` own the remaining follow-through checks for symbol-edit and usages defaults, diagnostics, trace capture, and validation sign-off.
- Any validation summary or trace recorded from Plan `02-02` must describe M12 as a **partial close** until those later plans land.
