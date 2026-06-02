# Architecture

**Analysis Date:** 2026-06-02

## Pattern Overview

**Overall:** Multi-surface runtime platform with a strict backend dependency direction (`gateway -> core -> infra`) plus an optional React operations UI.

**Key Characteristics:**
- One product exposes several entry surfaces: CLI, MCP server, HTTP API, SDK middleware, install scripts, and a browser dashboard.
- Domain behavior is capability-oriented inside `src/atelier/core/capabilities/`.
- Persistence, code-intel, embeddings, and sidecars are isolated under `src/atelier/infra/`.
- Host/plugin artifacts are generated or installed into `integrations/` from shared source material in `docs/agent-os/`.

## Layers

**Gateway Layer:**
- Purpose: User/host-facing entry points and adapters.
- Contains: Click CLI, MCP server, host configs, SDK wrappers, external integrations.
- Location: `src/atelier/gateway/`.
- Depends on: `core` orchestration and `infra` implementations through runtime/storage abstractions.

**Core Layer:**
- Purpose: Domain logic and product behavior.
- Contains: Capabilities, models, routing, rubrics, runtime orchestrator, service layer.
- Location: `src/atelier/core/`.
- Depends on: `infra` for concrete persistence/runtime utilities.

**Infra Layer:**
- Purpose: Concrete backends and process/runtime services.
- Contains: SQLite/Postgres stores, run ledgers, code-intel engines, sidecar bridges, embeddings.
- Location: `src/atelier/infra/`.
- Depends on: external libraries and OS/runtime services.

**Frontend / Distribution Layer:**
- Purpose: Visualization and installation surfaces.
- Contains: React UI, host integrations, install scripts, docs-site, Docker assets.
- Location: `frontend/`, `integrations/`, `scripts/`, `deploy/`.

## Data Flow

**CLI / MCP / SDK request path:**
1. A host enters through `src/atelier/gateway/cli/app.py`, `src/atelier/gateway/adapters/mcp_server.py`, or `src/atelier/gateway/sdk/local.py`.
2. Gateway code delegates to `src/atelier/gateway/adapters/runtime.py` (`ContextRuntime`) or directly to `src/atelier/core/runtime/engine.py` (`AtelierRuntimeCore`).
3. Core capabilities retrieve context, run routing/watchdog logic, or coordinate higher-level features such as swarm and proof gates.
4. Infra services persist traces/state and resolve code/memory/search backends through modules like `src/atelier/infra/storage/factory.py`, `src/atelier/infra/runtime/run_ledger.py`, and `src/atelier/core/capabilities/code_context/engine.py`.
5. Results are returned to the caller and optionally emitted to telemetry/ledger sinks.

**Frontend path:**
1. `frontend/src/App.tsx` defines routes and shell navigation.
2. `frontend/src/api.ts` calls the backend under `/api`.
3. FastAPI handlers in `src/atelier/core/service/api.py` return runtime, telemetry, swarm, and reporting data.

## Key Abstractions

- `ContextRuntime` (`src/atelier/gateway/adapters/runtime.py`) - main in-process host/runtime facade.
- `AtelierRuntimeCore` (`src/atelier/core/runtime/engine.py`) - capability orchestrator for context, routing, compression, proof gating, and tool supervision.
- `CodeContextEngine` (`src/atelier/core/capabilities/code_context/engine.py`) - large code-intel/index/query engine for symbols, routes, usages, and search packing.
- `RunLedger` / `RealtimeContextManager` (`src/atelier/infra/runtime/run_ledger.py`, `src/atelier/infra/runtime/realtime_context.py`) - persistent session/event tracking.
- `HostRegistry` (`src/atelier/gateway/hosts/registry.py`) - install-time host registration/fingerprinting.
- Swarm managers (`src/atelier/core/capabilities/swarm/capability.py`, `src/atelier/infra/runtime/swarm_worktree.py`) - parallel child-run orchestration and git worktree handling.

## Entry Points

**CLI Entry:**
- `src/atelier/gateway/cli/app.py`
- Trigger: `atelier ...`

**MCP Entry:**
- `src/atelier/gateway/adapters/mcp_server.py`
- Trigger: host MCP launch via `atelier-mcp`

**HTTP Service Entry:**
- `src/atelier/core/service/api.py`
- Trigger: FastAPI app / `atelier service start`

**SDK Entry:**
- `src/atelier/gateway/sdk/local.py`, `src/atelier/sdk/middleware.py`
- Trigger: embedding Atelier inside other agent runtimes

**Frontend Entry:**
- `frontend/src/main.tsx`, `frontend/src/App.tsx`
- Trigger: Vite dev/build or Docker frontend service

## Error Handling

**Strategy:** surface explicit domain/framework errors on core paths, but keep optional integrations fail-open when the product should continue operating.

**Patterns:**
- Service auth raises `HTTPException` with precise status codes (`src/atelier/core/service/auth.py`).
- Storage/runtime factories raise explicit `ValueError`/unavailable exceptions on unsupported backends (`src/atelier/infra/storage/factory.py`, `src/atelier/infra/internal_llm/*.py`).
- Optional integrations often swallow/log exceptions to avoid taking down the core loop (`src/atelier/gateway/integrations/langfuse.py`, `src/atelier/gateway/integrations/openmemory.py`).

## Cross-Cutting Concerns

- Telemetry/session accounting begins in both CLI and MCP entrypoints (`src/atelier/gateway/cli/app.py`, `src/atelier/gateway/adapters/mcp_server.py`).
- Workspace/root resolution separates runtime state from git-tracked lessons (`src/atelier/core/foundation/paths.py`).
- Generated host instruction surfaces must stay in sync with `docs/agent-os/` (`CLAUDE.md`, `Makefile`, `scripts/sync_agent_context.py`).
- Swarm, install, and plugin flows couple filesystem, git, and subprocess behavior across multiple directories (`scripts/install.sh`, `src/atelier/core/capabilities/swarm/capability.py`, `integrations/claude/plugin/hooks/`).

---

*Architecture analysis: 2026-06-02*
*Update when major patterns or surfaces change*
