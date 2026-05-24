# Codebase Concerns

**Analysis Date:** 2025-01-27

---

## Dead Code / Orphaned Modules

### `PrefixCachePlanner` — exported but never called

- **Files:** `src/atelier/core/capabilities/prefix_cache/planner.py`, `src/atelier/core/capabilities/prefix_cache/diagnostics.py`, `src/atelier/core/capabilities/prefix_cache/__init__.py`
- **Issue:** `PrefixCachePlanner`, `PrefixCachePlan`, and `PrefixCacheDiagnostics` are fully implemented, exported in `__init__.py`, and have no callers anywhere outside the `prefix_cache/` package. The designed abstraction for planning static/dynamic prompt splits and tracking cache hit ratios sits entirely idle.
- **Impact:** Zero test coverage, zero production callsites. Any refactoring of `compile_prompt` or block stability models can silently break this module with no signal.
- **Confirm:** `grep -rn "PrefixCachePlanner\|PrefixCachePlan\b" src/ | grep -v "prefix_cache/"` returns empty.
- **Fix approach:** Either wire into `tool_route` execution path (replacing `_prefix_cache_diagnostics_from_ledger`'s ad-hoc reconstruction) or delete the module. Do not keep as dead exported API.

### `_prefix_cache_diagnostics_from_ledger` — duplicates `PrefixCacheDiagnostics` logic with a known gap

- **File:** `src/atelier/gateway/adapters/mcp_server.py` line 888
- **Issue:** This private function in `tool_route` reconstructs prefix cache metrics from raw `llm_call` ledger events, duplicating the purpose of `PrefixCacheDiagnostics`. Crucially, it **always returns `avg_dynamic_tokens: 0`** (lines 897 and 919) — the field is hardcoded to zero in both the empty-events and populated code paths. No `dynamic_tokens` data is ever surfaced to callers.
- **Impact:** `tool_route` responses always report `avg_dynamic_tokens: 0` regardless of actual token splits, making the metric meaningless for operators optimizing prompt composition.
- **Fix approach:** Replace the ad-hoc function with `PrefixCacheDiagnostics.record_plan()` calls fed from proper `PrefixCachePlan` output, which tracks both prefix and dynamic tokens correctly.

### `compile_prompt` — used only by its own wrapper capability

- **File:** `src/atelier/core/capabilities/prompt_compilation/compiler.py` line 128
- **Issue:** `compile_prompt` is called from two places: `PromptCompilationCapability` (the legitimate wrapper in `capability.py`) and `PrefixCachePlanner.plan()` (dead code, see above). It is not called from any execution path in the gateway, service, or runtime layers.
- **Impact:** `PromptCompilationCapability` itself is a thin wrapper that is also not called outside tests. The entire prompt compilation pipeline (`prompt_compilation/` + `prefix_cache/`) is untested by integration and unconnected to actual agent execution.
- **Verify:** Tests in `tests/core/capabilities/prompt_compilation/test_compiler.py` exist for `compile_prompt` directly, but `PromptCompilationCapability` and `PrefixCachePlanner` have zero test files.

---

## Implementation Gaps

### Ingestion pipeline does not persist to store

- **Files:** `src/atelier/core/service/ingest_session.py` line 64, `src/atelier/core/service/ingest_session_directory.py` line 67
- **Issue:** Both `ingest_session_file` functions reconstruct a `RunLedger` from imported session data but then return immediately without writing anything to the store. Both contain `# TODO: Store reconstructed ledger events as traces.`
- **Impact:** The `atelier session ingest` command and the background worker (`src/atelier/core/service/worker.py`) appear to work but silently discard all session data. Imported sessions never become searchable traces.
- **Fix approach:** After ledger reconstruction, call `store.record_trace(...)` for each meaningful ledger event. The pattern is already used in `LocalClient.record_trace()`.

### `post_validation` hook does not record outcomes

- **File:** `src/atelier/core/runtime/engine.py` line 781–783
- **Issue:** `post_validation()` is defined as a hook to record validation pass/fail in the ledger but contains only `pass  # Extend to record pass/fail in ledger`.
- **Impact:** Validation outcomes from rubric gates and quality checks are not persisted to the run ledger. This means no historical record of which validations passed or failed for any given run.

### `pack` CLI command is commented out

- **File:** `src/atelier/gateway/cli/__main__.py` line 30–31
- **Issue:** The `atelier` CLI's minimal entrypoint contains a `TODO: Add pack commands once they're refactored` comment with the import commented out.
- **Impact:** The standalone `atelier` CLI entry point (different from the full CLI in `cli.py`) exposes no commands at all — it is a click group with no subcommands.
- **Fix approach:** Wire the full CLI group from `cli.py` into the `__main__` entry or complete the pack refactor.

---

## Missing Integrations

### `adapters/__init__.py` exports nothing — doc examples are broken

- **File:** `src/atelier/gateway/adapters/__init__.py`
- **Issue:** The file contains only `__all__ = []`. Every adapter module (`openhands_adapter.py`, `aider_adapter.py`, `sweagent_adapter.py`, `continue_adapter.py`, `langgraph_adapter.py`) documents its usage with `from atelier.gateway.adapters import OpenHandsAdapter, OpenHandsConfig` etc., but these imports will fail at runtime because `__init__.py` exports nothing.
- **Impact:** Any user following the documented SDK usage pattern gets an `ImportError`. The adapters can only be imported via direct submodule paths (`from atelier.gateway.adapters.openhands_adapter import OpenHandsAdapter`).
- **Fix approach:** Add explicit re-exports to `__init__.py` for all public adapter classes and config models.

### `http_api.py` is documented but missing

- **File:** `src/atelier/gateway/adapters/AGENT_README.md` (references `http_api.py` as a key entry point)
- **Issue:** `AGENT_README.md` lists `http_api.py` as a key entry point ("HTTP API adapter") but the file does not exist.
- **Impact:** Any code or documentation referring to an HTTP API adapter surface has no implementation.

### LangChain and OpenAI Agents SDK adapters — not implemented

- **File:** `src/atelier/gateway/adapters/` (directory)
- **Issue:** `AgentAdapter` base class supports OpenHands, SWE-agent, Aider, Continue, and LangGraph. There is no `langchain_adapter.py` or `openai_agents_adapter.py`. The dependency tree (`pyproject.toml` optional extras) does not include `langchain` or `openai-agents`.
- **Impact:** The two most widely-used Python agent frameworks have no first-class adapter despite `AgentAdapter` being designed as the extension point.

### SWE-bench harness — all real agent runners raise `NotImplementedError`

- **File:** `src/benchmarks/swe/agent_runner.py` line 139
- **Issue:** `build_agent()` returns `_UnsupportedAgent` for all hosts except `mock`. All real hosts (`claude`, `codex`, `opencode`, `copilot`, `antigravity`) raise `NotImplementedError` with a message saying to "implement an adapter."
- **Impact:** The SWE-bench harness only functions with the deterministic mock agent. All published benchmark comparisons using this harness are based on mock data, not real agent runs against real tasks.

---

## Technical Debt

### `mcp_server.py` — pervasive module-level global state

- **File:** `src/atelier/gateway/adapters/mcp_server.py` lines 152–160, 495–516
- **Issue:** The MCP server maintains 10+ module-level mutable singletons (`_current_ledger`, `_realtime_ctx`, `_product_session_id`, `_runtime_cache`, `_remote_client`, `_context_budget_recorder`, `_last_plan_hash_by_session`, etc.) mutated via `global` statements throughout the file.
- **Impact:** Test isolation requires importing and calling a private function `_reset_runtime_cache_for_testing()` — this pattern leaks into 4+ test files (`test_edit_ab_real.py`, `test_shell_ab_real.py`, `test_context_mcp_handler.py`, `test_mcp_tool_handlers.py`). Any future parallelism or multi-session support will require significant rework.
- **Fix approach:** Encapsulate runtime state in a `MCPServerState` dataclass, pass it as a dependency to tool functions instead of using module globals.

### God-object files

- **Files:**
  - `src/atelier/gateway/adapters/cli.py` — **8,988 lines**
  - `src/atelier/core/service/api.py` — **5,812 lines**
  - `src/atelier/core/capabilities/code_context/engine.py` — **6,291 lines**
  - `src/atelier/gateway/adapters/mcp_server.py` — **4,855 lines**
  - `src/atelier/core/capabilities/plugin_runtime.py` — **1,918 lines** (single-file capability)
- **Issue:** These files contain entire subsystems in a single module. `cli.py` implements the complete CLI surface for all command groups; `api.py` implements the entire service HTTP layer; `engine.py` implements all code context analysis.
- **Impact:** High cognitive load for changes, high merge conflict risk, difficult to test in isolation, and slow import times. `cli.py` at 9K lines is likely the single largest source file in the codebase.
- **Fix approach:** Extract command groups from `cli.py` into per-group modules. Extract route handlers from `api.py` into feature modules. Extract `engine.py` analysis phases into separate files.

### Inconsistent optional dependency handling

- **Files:** `src/atelier/core/capabilities/context_reuse/capability.py` lines 35–47, `src/atelier/core/capabilities/context_compression/deduplication.py` lines 10–12
- **Issue:** `context_reuse` and `context_compression` use try/except to conditionally import `networkx`, `scipy`, `hnswlib`, and `blake3` (with graceful None fallbacks). However, `context_reuse` uses `hnswlib` and `scipy` which are **not listed** in `pyproject.toml` optional extras at all. If these packages are absent, `context_reuse` silently degrades without any user warning.
- **Impact:** Capabilities silently disable themselves with no user-visible error. Operators may believe context reuse is working when the HNSW index is not actually being built.
- **Fix approach:** Add `hnswlib` and `scipy` to an optional extra group in `pyproject.toml`. Log a clear warning when optional capabilities degrade due to missing dependencies.

### `# type: ignore` suppressions — 46 instances

- **Scope:** `grep -rn "# type: ignore" src/` — 46 occurrences across production code
- **Issue:** Heavy use of `type: ignore` comments suppresses type checker feedback. Concentrations appear in `cli.py`, `mcp_server.py`, `context_reuse/capability.py`, and `tool_supervision/capability.py`.
- **Impact:** Silent type errors in production paths; capability of static analysis is degraded.

---

## Known Test Issues

### Two tests permanently skipped: marketplace file missing

- **File:** `tests/gateway/test_agent_cli_install_artifacts.py` lines 260, 266
- **Issue:** `@pytest.mark.skip(reason="Marketplace file missing from repo root")` — two tests for marketplace-related CLI behavior are permanently disabled because the artifact doesn't exist in the repo.
- **Impact:** Marketplace install paths are untested.

### `test_read_ab_real.py` — regression fallback documented in comment

- **File:** `tests/benchmarks/test_read_ab_real.py` line 271
- **Issue:** A comment reads: *"Sanity check: the seed run must produce N >= len(FIXTURES) measurement rows in savings_calibration.jsonl. Otherwise the harness is silently broken and we're back to magic constants."* Multiple tests in this file call `pytest.xfail(f"fixture missing: {fixture}")` when the calibration file is absent.
- **Impact:** If the calibration file is not seeded before running benchmarks, tests silently xfail rather than erroring — a false green signal.

### `bench_cost.py` — all assertions test simulated data, not real measurements

- **File:** `benchmarks/mcp_tools/bench_cost.py`
- **Issue:** All token profiles in `TURN_PROFILES` are hand-authored constants (e.g., `naive_input_tokens=1_400`, `atelier_uncached_input_tokens=600`). The `_simulate_naive()` and `_simulate_atelier()` functions apply arithmetic formulas to these constants. The five test assertions (e.g., `test_atelier_cost_reduction_at_least_60pct`) validate math on hand-picked numbers rather than measuring real system behavior.
- **Impact:** This benchmark passes regardless of whether the actual runtime achieves any cost savings. It tests the simulation model's internal consistency, not Atelier's real performance.
- **Fix approach:** Replace or supplement with an integration fixture that runs the actual `tool_route` / context pipeline against real token-counted prompts and compares against a naive baseline.

---

## Test Coverage Gaps

### Zero test files for critical capability modules

The following capabilities have no test directory or test files anywhere in `tests/`:

| Capability | Path | Risk |
|---|---|---|
| `budget_optimizer` | `src/atelier/core/capabilities/budget_optimizer/` | CP-SAT optimization logic untested |
| `context_compression` | `src/atelier/core/capabilities/context_compression/` | Deduplication and sleeptime logic untested |
| `context_reuse` | `src/atelier/core/capabilities/context_reuse/` | HNSW similarity ranking untested |
| `failure_analysis` | `src/atelier/core/capabilities/failure_analysis/` | Core rescue path untested |
| `loop_detection` | `src/atelier/core/capabilities/loop_detection/` | Agent loop detection untested |
| `model_routing` | `src/atelier/core/capabilities/model_routing/` | Model tier routing logic untested |
| `prefix_cache` | `src/atelier/core/capabilities/prefix_cache/` | Both planner and diagnostics untested |
| `reporting` | `src/atelier/core/capabilities/reporting/` | Report generation untested |
| `semantic_file_memory` | `src/atelier/core/capabilities/semantic_file_memory/` | Semantic memory untested |

**High-risk untested paths:** `failure_analysis` (called on every rescue), `context_compression` (called on every compaction), `model_routing` (determines which LLM tier gets a request).

---

## Improvement Opportunities

### Wire `PrefixCacheDiagnostics` into `tool_route`

- **Files:** `src/atelier/gateway/adapters/mcp_server.py`, `src/atelier/core/capabilities/prefix_cache/diagnostics.py`
- **Opportunity:** Replace `_prefix_cache_diagnostics_from_ledger` (which returns hardcoded `avg_dynamic_tokens: 0`) with proper `PrefixCacheDiagnostics.record_plan()` calls fed from `PrefixCachePlanner` output. This would activate the designed abstraction and fix the data quality gap simultaneously.

### Session ingestion should write traces

- **Files:** `src/atelier/core/service/ingest_session.py`, `src/atelier/core/service/ingest_session_directory.py`
- **Opportunity:** Both TODO comments (lines 64 and 67) point to the same missing behavior. Completing these would make imported sessions discoverable via `atelier trace list` and available for failure analysis training.

### SWE-bench real-agent integration

- **File:** `src/benchmarks/swe/agent_runner.py`
- **Opportunity:** The harness is fully structured for real agents. Implementing at least one real adapter (e.g., `claude` or `codex` via subprocess) would allow genuine A/B benchmarking between vanilla and Atelier-instrumented modes, validating the cost-savings claims with real data.

### Extract CLI groups from `cli.py`

- **File:** `src/atelier/gateway/adapters/cli.py` (8,988 lines)
- **Opportunity:** Group commands are already logically separated (`trace_group`, `memory_group`, `benchmark_group`, etc.). Each group can be extracted to `src/atelier/gateway/cli/<group>.py` and imported into `cli.py`, reducing the file to an assembly module of ~200 lines.

### Populate `adapters/__init__.py` with public API

- **File:** `src/atelier/gateway/adapters/__init__.py`
- **Opportunity:** Add re-exports for all public adapter classes so docstring examples (`from atelier.gateway.adapters import OpenHandsAdapter, OpenHandsConfig`) work as written. Low effort, high usability impact.

---

*Concerns audit: 2025-01-27*
