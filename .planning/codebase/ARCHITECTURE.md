<!-- refreshed: 2026-06-08 -->

# Architecture

**Analysis Date:** 2026-06-08

## System Overview

Atelier is an **Agent Reasoning Runtime** — a Python package (`src/atelier/`) that
provides reusable reasoning procedures, failure rescue, context reuse, and rubric
verification for coding/product agents, plus a React analytics dashboard
(`frontend/`). The Python backend follows a strict three-layer dependency
direction: `gateway → core → infra`.

```text
┌─────────────────────────────────────────────────────────────┐
│                  GATEWAY  (agent-facing surfaces)            │
│            `src/atelier/gateway/`                            │
├──────────────────┬──────────────────┬───────────────────────┤
│   CLI            │   MCP / Adapters │   HTTP SDK / Hosts    │
│ `gateway/cli/`   │ `gateway/        │ `gateway/sdk/`        │
│                  │  adapters/`      │ `gateway/hosts/`      │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                     CORE  (domain logic)                    │
│  `core/runtime/engine.py`  ←  orchestrator                  │
│  `core/capabilities/`  (context reuse, routing, proof gate, │
│                         memory, code-intel, swarm, workflow)│
│  `core/foundation/`  (Pydantic models, store, paths)        │
│  `core/service/`  (FastAPI HTTP surface)                    │
│  `core/domains/`  `core/rubrics/`  `core/improvement/`      │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│              INFRA  (persistence + integrations)            │
│  `infra/storage/`   (SQLite / Postgres / vector)            │
│  `infra/runtime/`   (run ledger, cost tracker, realtime)    │
│  `infra/code_intel/` (SCIP, ast-grep, Zoekt, git history)   │
│  `infra/embeddings/` `infra/memory_bridges/`                │
│  `infra/internal_llm/` (litellm/ollama/openai clients)      │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│   STATE STORE:  `~/.atelier/` (or $ATELIER_ROOT)            │
│   runs/  session_stats/  workspaces/  live_savings_events   │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component            | Responsibility                                                                 | File                                         |
| -------------------- | ------------------------------------------------------------------------------ | -------------------------------------------- |
| Runtime orchestrator | Coordinates capabilities, rubrics, traces, evals, storage from one entry point | `src/atelier/core/runtime/engine.py`         |
| Capabilities         | Domain logic units (context reuse, routing, proof gating, memory, code-intel)  | `src/atelier/core/capabilities/`             |
| Foundation           | Pydantic models, store, paths, retriever, renderer, redaction                  | `src/atelier/core/foundation/`               |
| HTTP service         | FastAPI app exposing runtime over HTTP                                         | `src/atelier/core/service/api.py`            |
| CLI                  | `atelier` / `atl` command surface                                              | `src/atelier/gateway/cli/app.py`             |
| MCP server           | stdio JSON-RPC MCP tool server for Claude/Codex/Gemini                         | `src/atelier/gateway/adapters/mcp_server.py` |
| In-process adapter   | `ContextRuntime` façade for embedding the runtime                              | `src/atelier/gateway/adapters/runtime.py`    |
| SDK middleware       | LangChain/OpenAI/Anthropic/Gemini integration surfaces                         | `src/atelier/sdk/middleware.py`              |
| Storage backends     | SQLite / Postgres / vector persistence                                         | `src/atelier/infra/storage/`                 |
| Run ledger           | Append-only event/trace/token log per run                                      | `src/atelier/infra/runtime/run_ledger.py`    |
| Frontend dashboard   | React analytics UI over the HTTP API                                           | `frontend/src/`                              |

## Pattern Overview

**Overall:** Layered (hexagonal-leaning) architecture with a single runtime
orchestrator and pluggable capability modules.

**Key Characteristics:**

- Strict one-way dependency: `gateway → core → infra` (entry points never reach past core's public surface for business logic).
- Capability-oriented core: each feature is an isolated package under `core/capabilities/` exposing a capability class (e.g. `ContextReuseCapability`, `ProofGateCapability`) aggregated by `engine.AtelierRuntimeCore`.
- Multiple thin entry surfaces (CLI, MCP, HTTP, in-process SDK, host adapters) all delegate to the same core.
- Factory-based backend selection for storage and embeddings via environment variables.
- Append-only ledger + file-based state under `~/.atelier/` rather than a central DB server by default.

## Layers

**Gateway (`src/atelier/gateway/`):**

- Purpose: All agent-facing entry points; keep logic thin (dispatchers only).
- Location: `src/atelier/gateway/`
- Contains: `cli/` (Click app + commands), `adapters/` (MCP server, host adapters: aider, cursor, continue, langgraph, openhands, sweagent, hermes; `runtime.py` façade), `sdk/` (HTTP client/local/remote/mcp clients), `hosts/` (host registry + session parsers), `integrations/` (langfuse, openmemory, analytics).
- Depends on: `core/`
- Used by: external agents, CLI users, MCP hosts.

**Core (`src/atelier/core/`):**

- Purpose: Domain logic and orchestration.
- Location: `src/atelier/core/`
- Contains: `runtime/engine.py` (orchestrator), `capabilities/` (~60 feature packages), `foundation/` (models, store, retriever, renderer), `service/` (FastAPI api, auth, jobs, worker, sync, telemetry), `domains/` (domain loader/manager/builtin), `rubrics/`, `improvement/` (failure analyzer), `environment.py`.
- Depends on: `infra/`
- Used by: `gateway/`

**Infra (`src/atelier/infra/`):**

- Purpose: Persistence and external integrations.
- Location: `src/atelier/infra/`
- Contains: `storage/` (base/factory/sqlite_store/postgres_store/vector/memory_store/migrations), `runtime/` (run_ledger, cost_tracker, realtime_context, checkpoint, session_state, swarm_worktree, lifecycle), `code_intel/` (scip, astgrep, zoekt, cross_lang, git_history), `embeddings/` (local/ollama/openai/letta/null), `memory_bridges/` (letta_adapter, openmemory), `internal_llm/` (litellm/ollama/openai clients), `seed_playbooks/` (YAML reason blocks), `tree_sitter/`.
- Depends on: external services, filesystem.
- Used by: `core/`

## Data Flow

### Primary Run Path (in-process adapter)

1. Caller opens a run: `ContextRuntime().run(domain=..., task=..., tools=...)` (`src/atelier/gateway/adapters/runtime.py`)
2. Adapter delegates to `AtelierRuntimeCore` which assembles capabilities and store (`src/atelier/core/runtime/engine.py`)
3. `session.inject_reasoning_context()` retrieves & renders prior reason blocks/memory (`core/foundation/retriever.py`, `core/foundation/renderer.py`)
4. Agent executes; watchdogs + loop detection monitor (`core/capabilities/loop_detection/`, `core/foundation/watchdogs.py`)
5. `session.verify(result, rubric_id=...)` runs rubric gate (`core/foundation/rubric_gate.py`)
6. `session.record_trace()` appends events to the run ledger (`src/atelier/infra/runtime/run_ledger.py`)
7. `session.extract_candidate_blocks()` mines reusable reason blocks (`core/foundation/extractor.py`)

### HTTP / Dashboard Path

1. `create_app(store_root=...)` builds FastAPI app (`src/atelier/core/service/api.py`)
2. Routes call core capabilities and read storage backend (`infra/storage/factory.py`)
3. React frontend (`frontend/src/pages/*`) fetches JSON and renders analytics (Sessions, Savings, Insights, Memory, Swarm, Workflow, etc.)

### MCP / Host Path

1. Host (Claude/Codex/Gemini) launches `atelier mcp` stdio server (`src/atelier/gateway/adapters/mcp_server.py`)
2. MCP tool calls dispatch to core capabilities; results return as JSON-RPC.
3. Claude Code hooks (`integrations/claude/plugin/hooks/*.py`) emit savings/telemetry events into `~/.atelier/`.

**State Management:**

- Runtime state is file-based under `~/.atelier/` (or `$ATELIER_ROOT`): `runs/<session_id>.json`, `session_stats/<uuid>.json`, `live_savings_events.jsonl`, `workspaces/<hash>/session_state.json`, `smart_state.json`.
- Structured persistence via SQLite (default) or Postgres backend selected by `ATELIER_STORAGE_BACKEND`.

## Key Abstractions

**Capability:**

- Purpose: A self-contained unit of reasoning logic registered with the runtime.
- Examples: `src/atelier/core/capabilities/context_reuse/`, `.../proof_gate/`, `.../quality_router/`, `.../semantic_file_memory/`, `.../tool_supervision/`.
- Pattern: Capability class imported into `engine.AtelierRuntimeCore` (see `CAPABILITIES` class var) and composed at construction; a `CapabilityRegistry`/`CapabilityNode` graph exists at `core/capabilities/registry/graph.py`.

**Playbook / Reason Block seeds:**

- Purpose: Reusable procedural reasoning fragments.
- Examples: `src/atelier/infra/seed_playbooks/*.yaml`, `core/foundation/models.py` (`Playbook`).
- Pattern: Seeded from YAML, extracted from runs by `core/foundation/extractor.py`.

**Storage backend:**

- Purpose: Pluggable persistence (SQLite/Postgres/vector).
- Examples: `src/atelier/infra/storage/factory.py`, `sqlite_store.py`, `postgres_store.py`.
- Pattern: `create_store(root)` factory dispatching on `ATELIER_STORAGE_BACKEND`.

**Run ledger:**

- Purpose: Append-only event/trace record for a run.
- Examples: `src/atelier/infra/runtime/run_ledger.py`.
- Pattern: `LedgerEvent` records serialized to JSON; cost tracked via `cost_tracker.py`.

## Entry Points

**CLI (`atelier` / `atl`):**

- Location: `src/atelier/gateway/cli/app.py` (`cli`, `main`); subcommands in `gateway/cli/commands/`.
- Triggers: console scripts `atelier`, `atl` (pyproject `[project.scripts]`).
- Responsibilities: dispatch to core; thin command handlers.

**MCP server (`atelier mcp`):**

- Location: `src/atelier/gateway/adapters/mcp_server.py:main`.
- Triggers: stdio launch by MCP hosts.
- Responsibilities: expose runtime tools over JSON-RPC.

**HTTP service:**

- Location: `src/atelier/core/service/api.py:create_app` (run via `atelier runtime start`).
- Triggers: uvicorn/FastAPI.
- Responsibilities: HTTP surface for runtime + dashboard data.

**In-process SDK:**

- Location: `src/atelier/gateway/adapters/runtime.py` (`ContextRuntime`), `src/atelier/sdk/middleware.py` (`AtelierMiddleware`).
- Triggers: direct import by host frameworks (LangChain, OpenAI Agents, Anthropic, Gemini ADK).
- Responsibilities: wrap runtime behind framework-native hooks.

## Architectural Constraints

- **Threading:** Primarily synchronous Python; FastAPI service uses threads (`threading` in `api.py`) and the MCP server runs single-process stdio. No heavy multiprocessing in the core path; swarm work uses git worktrees (`infra/runtime/swarm_worktree.py`).
- **Global state:** Runtime state externalized to `~/.atelier/`; module-level `logger` objects per module. Backend selection driven by env vars (`ATELIER_STORAGE_BACKEND`, `ATELIER_ROOT`).
- **Dependency direction:** Enforced `gateway → core → infra`. Reaching upward (infra importing core, core importing gateway) is forbidden.
- **Environment:** All Python must run under `uv run` (no activated venv); requires Python ≥ 3.12.

## Anti-Patterns

### Logic in entry-point dispatchers

**What happens:** Putting business logic directly into `mcp_server.py` or `cli/commands/*.py`.
**Why it's wrong:** Violates the thin-gateway invariant; duplicates behavior across CLI/MCP/HTTP surfaces and bypasses the orchestrator.
**Do this instead:** Add a capability under `src/atelier/core/capabilities/` and call it from the dispatcher (see `engine.AtelierRuntimeCore`).

### Bypassing the storage factory

**What happens:** Instantiating `SQLiteStore`/`PostgresStore` directly in feature code.
**Why it's wrong:** Defeats backend selection and `ATELIER_STORAGE_BACKEND` configuration.
**Do this instead:** Use `create_store(root)` from `src/atelier/infra/storage/factory.py`.

### Editing generated files directly

**What happens:** Hand-editing `AGENTS.md`, host instruction files, or staged plugin dirs.
**Why it's wrong:** They are regenerated from `integrations/` sources and changes are lost.
**Do this instead:** Edit `integrations/agents/` or `integrations/shared/` then run `make sync-agent-context`.

## Error Handling

**Strategy:** Resilience-oriented — uses `tenacity` (retries) and `pybreaker` (circuit breakers) around external/LLM calls; `contextlib.suppress` for best-effort telemetry paths.

**Patterns:**

- LLM clients in `infra/internal_llm/` define explicit `exceptions.py` and `result.py` result types.
- Best-effort side effects (telemetry, savings) wrapped in `suppress(...)` so they never break the main path.

## Cross-Cutting Concerns

**Logging:** Standard library `logging` with per-module loggers (`logger = logging.getLogger(__name__)`).
**Validation:** Pydantic v2 models throughout `core/foundation/` and service schemas (`core/service/schemas.py`).
**Telemetry:** OpenTelemetry (api/sdk/otlp exporter) plus Prometheus client; redaction via `core/foundation/redaction.py`; frustration lexicon at `core/service/telemetry/frustration_lexicon.yaml`.
**Authentication:** Optional Bearer auth for the HTTP service (`core/service/auth.py`).

---

_Architecture analysis: 2026-06-08_
