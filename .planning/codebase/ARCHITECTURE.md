<!-- refreshed: 2025-05-25 -->
# Architecture

**Analysis Date:** 2025-05-25

## System Overview

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                           GATEWAY LAYER                                    │
│                                                                            │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │  mcp_server.py  │  │   cli.py     │  │   Agent Adapters             │  │
│  │  (stdio MCP,    │  │  (atelier    │  │  LangGraph / Aider / Codex   │  │
│  │   JSON-RPC)     │  │   CLI)       │  │  SWE-Agent / OpenHands       │  │
│  └────────┬────────┘  └──────┬───────┘  └──────────────┬───────────────┘  │
│           │                  │                          │                  │
│  ┌────────▼──────────────────▼──────────────────────────▼───────────────┐  │
│  │            runtime.py  (ContextRuntime — in-process façade)          │  │
│  │            gateway/sdk/  (AtelierClient — local / mcp / remote)      │  │
│  └────────────────────────────────┬──────────────────────────────────────┘  │
└───────────────────────────────────┼────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────────┐
│                             CORE LAYER                                      │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  runtime/engine.py  (AtelierRuntimeCore — capability orchestrator) │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  capabilities/                                                              │
│  ┌──────────────────┐ ┌───────────────────┐ ┌──────────────────────────┐   │
│  │ContextCompression│ │ ContextReuse      │ │ ModelRouting /           │   │
│  │ (TF-IDF, dedup,  │ │ (prior procedures │ │ QualityRouter            │   │
│  │  sleeptime LLM)  │ │  + failure sigs)  │ │ (5-tier route selection) │   │
│  └──────────────────┘ └───────────────────┘ └──────────────────────────┘   │
│  ┌──────────────────┐ ┌───────────────────┐ ┌──────────────────────────┐   │
│  │ ToolSupervision  │ │ ProofGate         │ │ PrefixCache              │   │
│  │ (redundancy det, │ │ (cost-quality     │ │ (static/dynamic split,   │   │
│  │  obs. cache)     │ │  gate + evals)    │ │  KV-cache planning)      │   │
│  └──────────────────┘ └───────────────────┘ └──────────────────────────┘   │
│  ┌──────────────────┐ ┌───────────────────┐ ┌──────────────────────────┐   │
│  │ SemanticFile     │ │ LoopDetection     │ │ FailureAnalysis /        │   │
│  │ Memory           │ │ (dead-end detect, │ │ ArchivalRecall           │   │
│  │ (symbol maps)    │ │  FSM + patterns)  │ │ (root-cause clustering)  │   │
│  └──────────────────┘ └───────────────────┘ └──────────────────────────┘   │
│  ┌──────────────────┐ ┌───────────────────┐ ┌──────────────────────────┐   │
│  │ CodeContext      │ │ PromptCompilation │ │ CrossVendorRouting       │   │
│  │ engine.py (SCIP, │ │ (compiler.py,     │ │ (advisor, policy,        │   │
│  │  Zoekt, astgrep) │ │  lint rules)      │ │  router)                 │   │
│  └──────────────────┘ └───────────────────┘ └──────────────────────────┘   │
│                                                                             │
│  foundation/       (models, store, renderer, retriever, routing_models,    │
│                     rubric_gate, watchdog_profiles, paths, extractor)       │
│  service/api.py    (FastAPI HTTP surface — atelier runtime start)           │
│  rubrics/          (YAML rubric definitions)                                │
│  domains/          (domain-specific loader + builtin domains)               │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────────┐
│                            INFRA LAYER                                      │
│                                                                             │
│  storage/      (SQLite/Postgres ContextStore, MemoryStore, VectorStore)    │
│  runtime/      (RunLedger, Checkpoint, RealtimeContextManager,             │
│                 CostTracker, SessionReport, OutcomeCapture)                 │
│  code_intel/   (SCIP index, ast-grep, Zoekt, git history, cross-lang)     │
│  embeddings/   (local, OpenAI, Letta embedders)                            │
│  memory_bridges/ (Letta, OpenMemory adapters)                              │
│  tree_sitter/  (AST parsing)                                               │
│  internal_llm/ (internal LLM routing)                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │    ~/.atelier/ (state root)    │
                    │  runs/  session_stats/         │
                    │  workspaces/  smart_state.json │
                    │  checkpoints/  live_savings_   │
                    │  events.jsonl                  │
                    └───────────────────────────────┘
```

## Layer Boundaries

**Strict dependency direction:** `gateway/` → `core/` → `infra/`

| Layer | Purpose | Allowed Dependencies |
|-------|---------|----------------------|
| `gateway/` | All agent-facing entry points; dispatch only | `core/`, `infra/` |
| `core/` | Domain logic, capabilities, models, service contracts | `infra/` (minimal), stdlib |
| `infra/` | Persistence, storage, code index, embeddings | `core/` foundation models |

**Key invariant:** New capabilities go in `core/capabilities/`, never in `mcp_server.py` or `cli.py`. Those files are dispatchers only.

**Forbidden:**
- `core/` must NOT import from `gateway/`
- `infra/` must NOT import from `gateway/`
- Host-specific behavior belongs in `gateway/hosts/` or `integrations/`

## Entry Points

**MCP Server (primary agent interface):**
- Location: `src/atelier/gateway/adapters/mcp_server.py` (4855 lines)
- Protocol: stdio JSON-RPC, MCP protocol version `2024-11-05`
- Clients: Claude Code, Codex, Gemini
- Server name: `atelier-context`
- Auto-spawns background worker for async operations

**CLI:**
- Location: `src/atelier/gateway/adapters/cli.py` (8988 lines — the largest file)
- Framework: Click
- Entrypoint: `uv run atelier ...`
- Supports `--json` flag on all data-returning commands

**FastAPI HTTP Service:**
- Location: `src/atelier/core/service/api.py` (5812 lines)
- Launch: `atelier runtime start`
- Auth: Bearer token (`src/atelier/core/service/auth.py`)
- Schemas: `src/atelier/core/service/schemas.py`

**In-process SDK Façade:**
- Location: `src/atelier/gateway/adapters/runtime.py`
- Class: `ContextRuntime` — context manager pattern for SDK usage
- Pattern: `with rt.run(domain=..., task=...) as session:`

**Agent Adapters:**
- `src/atelier/gateway/adapters/langgraph_adapter.py` — LangGraph nodes/edges
- `src/atelier/gateway/adapters/aider_adapter.py`
- `src/atelier/gateway/adapters/continue_adapter.py`
- `src/atelier/gateway/adapters/sweagent_adapter.py`
- `src/atelier/gateway/adapters/openhands_adapter.py`
- `src/atelier/gateway/adapters/remote_client.py`
- All extend `AdapterBase` from `src/atelier/gateway/adapters/adapter_base.py`
- Adapter modes: `shadow` | `suggest` | `enforce`

## MCP Tool Surface

Tools registered via `@mcp_tool(name=...)` decorator in `mcp_server.py`:

| Tool Name | Purpose |
|-----------|---------|
| `context` | Inject reasoning context for the current session |
| `route` | Get prospective model routing recommendation (5-tier) |
| `rescue` | Failure analysis and recovery suggestions |
| `trace` | Record execution trace event |
| `verify` | Run rubric gate check |
| `memory` | Block-level memory operations (upsert, get, archive) |
| `read` | Smart file read with tool supervision |
| `edit` | Batch edit with post-edit hooks and symbol rename |
| `sql` | SQL execution with safety inspection |
| `code` | Code intelligence (symbol lookup, SCIP navigation) |
| `grep` | Supervised grep |
| `search` | Semantic/lexical hybrid search |
| `compact` | Context compression (explicit trigger) |
| `shell` | Supervised shell execution with circuit breaker |

Auto-compact triggers at 80% context utilization (configurable via `AUTO_COMPACT_THRESHOLD`). Handover advisory at 95%.

## Core Capabilities

All capabilities are lazy-loaded via `src/atelier/core/capabilities/__init__.py`.

### Context Compression — `core/capabilities/context_compression/`
- `capability.py`: `ContextCompressionCapability`
- Strategy: TF-IDF event scoring → recency weighting → semantic deduplication → budget-aware truncation
- Uses `sleeptime.py` for optional LLM-assisted summarization
- Input: `RunLedger`, token budget; Output: `CompressionResult` with provenance

### Context Reuse — `core/capabilities/context_reuse/`
- `capability.py`: `ContextReuseCapability` (983 lines)
- Retrieves prior successful procedures and failure signatures for the current task

### Model / Quality Routing — `core/capabilities/model_routing/`, `core/capabilities/quality_router/`
- `router.py`: `ModelRouter` — 5-tier routing: `deterministic` → `local_slm` → `cheap_llm` → `frontier_llm` → `human_review`
- Tool cost classification: cheap tools (bash, read, grep), medium (edit, verify), expensive (agent, spawn)
- Session-phase classification: exploration vs. execution vs. verification phases

### Tool Supervision — `core/capabilities/tool_supervision/`
- `capability.py`: `ToolSupervisionCapability`
- Submodules: `search_read.py`, `smart_search.py`, `batch_edit.py`, `bash_exec.py`, `sql_tool.py`, `symbol_edit.py`, `anomaly.py`, `circuit_breaker.py`, `rich_edit.py`
- Tracks redundancy, observation cache hits, efficiency metrics

### Proof Gate — `core/capabilities/proof_gate/`
- `capability.py`: `ProofGateCapability`
- Combines context savings metrics, routing evals, and trace confidence into a pass/fail decision

### Prefix Cache — `core/capabilities/prefix_cache/`
- `planner.py`: `PrefixCachePlanner` — splits prompt into `static_prefix` (STATIC/SESSION stability) vs `dynamic_state` (BRANCH/TURN/VOLATILE)
- `diagnostics.py`: `PrefixCacheDiagnostics` — tracks per-turn cache hit ratio, invalidation frequency
- Depends on `prompt_compilation/compiler.py` for `compile_prompt`

### Semantic File Memory — `core/capabilities/semantic_file_memory/`
- `capability.py`: `SemanticFileMemoryCapability` (627 lines)
- Maintains semantic summaries and symbol maps for local files

### Loop Detection — `core/capabilities/loop_detection/`
- `capability.py`: `LoopDetectionCapability`
- `patterns.py`, `models.py`, `rescue.py`, `signatures.py`
- Uses FSM (`monitors/fsm.py`) for state tracking

### Failure Analysis — `core/capabilities/failure_analysis/`
- `capability.py`: `FailureAnalysisCapability`
- Root-cause clustering of repeated failures

### Archival Recall — `core/capabilities/archival_recall/`
- `capability.py`: `ArchivalRecallCapability`
- Symbol-level recall via `symbol_recall.py`

### Code Context Engine — `core/capabilities/code_context/`
- `engine.py` (6291 lines — second largest file)
- Integrates SCIP index, ast-grep, Zoekt search, tree-sitter AST
- Multi-language support: `python_ast.py`, `typescript_ast.py`, `treesitter_ast.py`

### Prompt Compilation — `core/capabilities/prompt_compilation/`
- `compiler.py`: `compile_prompt` — assembles `PromptBlock` list into structured prompt
- `models.py`: `PromptBlock`, `BlockKind`, `Stability` (STATIC/SESSION/BRANCH/TURN/VOLATILE)
- `lint_rules/`: lint validation for prompt structure

### Additional Capabilities
- `budget_optimizer/` — `PromptBudgetOptimizer`, `BudgetPlan`, `ContextBlock`
- `cross_vendor_routing/` — `advisor.py`, `policy.py`, `router.py`
- `cross_vendor_memory/` — Cross-vendor memory synchronization
- `governance/` — Policy enforcement
- `lesson_promotion/` — `LessonPromoterCapability`
- `telemetry/` — `TelemetrySubstrate`, `TelemetryEvent`
- `repo_map/` — Repository structure mapping
- `optimization/`, `optimization_audit/` — Query optimization
- `sync/` — State synchronization
- `team/` — Team-level memory
- `style_import/` — Code style learning
- `starter_packs/` — Domain starter context packs
- `session_optimizer.py` — Per-session optimization
- `plugin_runtime.py` (1918 lines) — Plugin execution runtime

## Runtime Orchestrator

**Class:** `AtelierRuntimeCore` in `src/atelier/core/runtime/engine.py` (940 lines)

Instantiates all core capabilities at construction time from a single root path:
```python
self.store = ContextStore(root)          # SQLite-backed context store
self.context_reuse = ContextReuseCapability(store, root)
self.semantic_memory = SemanticFileMemoryCapability(root)
self.loop_detection = LoopDetectionCapability()
self.quality_router = QualityRouterCapability(store, root, loop_detection=...)
self.tool_supervision = ToolSupervisionCapability(root)
self.context_compression = ContextCompressionCapability()
self.failure_analysis = FailureAnalysisCapability(store, context_reuse)
self.proof_gate = ProofGateCapability(root)
```

## Data Flow

### MCP Tool Call (primary path)

1. **Agent** sends JSON-RPC `tools/call` over stdio → `mcp_server.py`
2. `mcp_server.py` dispatches to registered `@mcp_tool` handler function
3. Handler calls lazy-initialized singletons: `_runtime()`, `_get_ledger()`, `_get_realtime_context()`, `_memory_store()`
4. Capability invoked (e.g., `ContextCompressionCapability.compress_with_provenance(ledger, ...)`)
5. Infra layer read/write: `RunLedger.append_event()`, `ContextStore.upsert_block()`, `RealtimeContextManager.ingest()`
6. Response serialized to JSON and written to stdout

### Session Lifecycle

1. **Session start**: `_emit_mcp_session_start()` initializes `RunLedger`, `RealtimeContextManager`
2. **Each tool call**: ledger records event, cost tracker updates, realtime context ingests signal
3. **Auto-compact**: background monitor checks utilization at each turn; fires `compact` when >80%
4. **Handover**: advisory emitted at >95% utilization
5. **Session end**: `_emit_mcp_session_end()` flushes ledger to `~/.atelier/runs/<session_id>.json`

### Context Injection (context tool)

1. Agent calls `context` tool at session start
2. `mcp_server.py` → `_bootstrap_context_status(root)` → `AtelierRuntimeCore`
3. `render_context_for_agent()` from `core/foundation/renderer.py` assembles prompt blocks
4. Token budget enforced via `count_tokens()` from `core/foundation/retriever.py`
5. Retrieved blocks: reasonblocks, memory facts, archival passages, semantic file summaries

### Claude Code Hook Flow

1. Claude Code fires hook event (pre_tool, post_tool, stop, session_start)
2. Hook script in `integrations/claude/plugin/hooks/` executes
3. Writes event to `~/.atelier/live_savings_events.jsonl`
4. Stop hook reads `~/.atelier/session_stats/<uuid>.json` and displays savings

## Key Patterns

### Tool Registry Pattern (MCP)
```python
@mcp_tool(name="compact", description="...")
def tool_compact_context(session_id: str | None = None) -> Any:
    ...
```
The `@mcp_tool` decorator registers the function in the `TOOLS` dict, auto-derives the MCP input schema from type annotations, and controls visibility to LLM via `mcp_tool_visible_to_llm()`.

### Capability as Stateless Service
Most capabilities are stateless objects instantiated once by `AtelierRuntimeCore`:
```python
capability = ContextCompressionCapability()  # no state in __init__
result = capability.compress_with_provenance(ledger, token_budget=8000)
```
State lives in the `RunLedger` (passed in) and `ContextStore` (injected at construction).

### Lazy Singleton Initialization (MCP layer)
```python
_runtime_cache: AtelierRuntimeCore | None = None
def _runtime() -> AtelierRuntimeCore:
    global _runtime_cache
    if _runtime_cache is None:
        _runtime_cache = AtelierRuntimeCore(root=_atelier_root())
    return _runtime_cache
```
Pattern used for: `_runtime()`, `_get_ledger()`, `_get_realtime_context()`, `_memory_store()`, `_archival_recall()`.

### Adapter Mode Pattern
All ecosystem adapters support three modes via `AdapterMode = Literal["shadow", "suggest", "enforce"]`:
- `shadow`: collect data only, never block
- `suggest`: return warnings, agent decides
- `enforce`: block on rubric failures

### Rubric Gate Pattern
Declarative YAML rubrics in `core/rubrics/` are evaluated via `core/foundation/rubric_gate.py`:
```python
result = run_rubric(rubric_id="rubric_code_change", checks={...})
```
Available rubrics: `rubric_code_change`, `rubric_code_review`, `rubric_debugging_task`, `rubric_state_change_safety`, `rubric_verification_ladder`, `rubric_knowledge_authoring`, `rubric_change_gate_discipline`, `rubric_source_of_truth_change`, `rubric_atelier_retrieval_recall`.

### 5-Tier Model Routing
```
deterministic → local_slm → cheap_llm → frontier_llm → human_review
```
Advisory only — the host CLI retains actual model selection authority.

### Prompt Block Stability Hierarchy
Blocks are classified by `Stability` for prefix cache optimization:
- `STATIC` — system prompt, never changes
- `SESSION` — session metadata, changes once per session
- `BRANCH` — task/domain-scoped, changes per branch
- `TURN` — changes every turn
- `VOLATILE` — ephemeral, never cached

## Foundation Layer

Key files in `src/atelier/core/foundation/`:

| File | Purpose |
|------|---------|
| `models.py` | Core Pydantic models: `Trace`, `ReasonBlock`, `Rubric`, `LedgerEvent`, `ToolCall`, `RescueResult`, `RubricResult` |
| `store.py` (1824 lines) | `ContextStore` — SQLite-backed store for blocks, traces, facts |
| `retriever.py` | `retrieve()`, `score_block()`, `count_tokens()`, `render_memory_for_agent()` |
| `renderer.py` | `render_context_for_agent()`, `render_block_markdown()`, `render_rubric_result()` |
| `routing_models.py` | `RouteDecision`, `StepType`, `TaskType` |
| `rubric_gate.py` | `run_rubric()` — evaluates YAML rubric against a checks dict |
| `watchdog_profiles.py` | `active_watchdog_weights()` — per-domain watchdog configuration |
| `paths.py` | `default_store_root()`, `resolve_workspace_root()` — `~/.atelier/` paths |
| `extractor.py` | `extract_candidate()` — extracts `CandidateBlock` from agent output |
| `memory_models.py` | `MemoryBlock`, `ArchivalPassage` |
| `redaction.py` | `redact()` — strips sensitive data from memory inputs |

## Infra Persistence

### RunLedger — `infra/runtime/run_ledger.py`
Append-only event log for a single agent run. Tracks: events, plan, files touched, tools called, commands run, errors, hypotheses, verified facts, open questions, budgets, costs. Persisted to `~/.atelier/runs/<session_id>.json`.

### ContextStore — `core/foundation/store.py` (1824 lines)
SQLite-backed store for ReasonBlocks, traces, memory facts, rubric results. Primary retrieval engine for context injection.

### Storage Backends — `infra/storage/`
- `sqlite_store.py` / `sqlite_memory_store.py` — default local storage
- `postgres_store.py` (1235 lines) — production Postgres backend
- `memory_store.py` — abstract base
- `vector.py` — vector similarity search
- `factory.py` — selects backend based on config

### Checkpoints — `infra/runtime/checkpoint.py`
Content-addressed step snapshots at `~/.atelier/checkpoints/<session_id>/<step_id>.json`. Enables resumable execution after network failure or budget exhaustion.

### Code Intelligence — `infra/code_intel/`
Integrates: SCIP (semantic code index), ast-grep (structural search), Zoekt (full-text), git history, cross-language analysis.

## Error Handling

**Strategy:** Defensive — capabilities catch and log errors, return degraded results rather than propagate exceptions to the MCP layer.

**Patterns:**
- `contextlib.suppress(Exception)` used extensively in capability code to avoid crashing the MCP server on non-critical failures
- `MemoryConcurrencyError`, `MemorySidecarUnavailable` are explicitly caught in `mcp_server.py` and surfaced as tool error responses
- `circuit_breaker.py` in tool supervision prevents cascading failures from repeated shell/SQL errors

## Cross-Cutting Concerns

**Logging:** Python `logging` module throughout. Logger per module: `logger = logging.getLogger(__name__)`.

**Validation:** Pydantic v2 models (`pydantic>=2.6`) for all data contracts. `ConfigDict(extra="forbid")` on adapter/config models.

**Token counting:** `tiktoken` (`count_tokens()` in `core/foundation/retriever.py`) used for all budget enforcement.

**Telemetry:** OpenTelemetry (`opentelemetry-api/sdk/exporter`) + Langfuse in `gateway/integrations/`.

**Cost tracking:** `CostTracker` in `infra/runtime/cost_tracker.py`, `usage_cost_usd()` in `core/capabilities/pricing.py` with `pricing.yaml` model cost table.

---

*Architecture analysis: 2025-05-25*
