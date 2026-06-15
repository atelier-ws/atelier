<!-- GSD:project-start source:PROJECT.md -->

## Project

**Atelier**

Atelier is a brownfield agent runtime being reset into a benchmark-first terminal coding agent: a slimmer execution core that preserves Atelier's strongest context, memory, code-intel, tracing, and host-enforcement capabilities while maximizing solved-rate on hard terminal tasks. The target shape is a hybrid of Eval and Augment: Eval-grade execution discipline, Augment-grade context quality pressure, and Atelier's own code-intel/memory strengths, built as a retrofit rather than a rewrite.

**Core Value:** Achieve the highest solved-rate on frozen terminal-bench-style coding tasks, with non-inferior quality and lower cost where possible.

### Constraints

- **Architecture**: Brownfield retrofit on the existing `gateway -> core -> infra` structure — preserve working foundations and minimize disruptive rewrites.
- **Product**: Terminal-first core — prioritize the default terminal task loop over secondary UI or platform expansion.
- **Quality**: Do not regress current memory, code-intel, tracing, or host-enforcement strengths — those are already real product advantages.
- **Routing**: Enforce routing only where Atelier owns execution first — top-level host chat remains shadow/advisory until parity is measured.
- **Validation**: Success claims require paired benchmark evidence with raw artifacts — UX savings counters alone are not sufficient proof.
- **Benchmark Focus**: Every roadmap phase must improve solved-rate, grounding, execution coherence, or cost-under-parity on terminal-bench-style tasks — otherwise defer it.
- **Scope**: Surface cuts require parity review first — no speculative pruning of existing capabilities.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python >=3.11 - Core runtime, CLI, MCP server, HTTP service, host integrations, and most benchmarks live under `src/atelier/`, `src/benchmarks/`, `scripts/`, and `tests/`.
- TypeScript 5.5.3 - Optional React frontend in `frontend/src/`.
- Bash - Install/bootstrap and verification flows in `scripts/install.sh`, `scripts/install_claude.sh`, and `scripts/verify_*.sh`.
- YAML / JSON / Markdown - Host configs in `src/atelier/gateway/hosts/configs/*.yaml`, workflow docs under `docs/`, and generated agent surfaces in `integrations/`.

## Runtime

- Python/uv runtime - `pyproject.toml` and `uv.lock` drive the backend environment; repository guidance requires `uv run ...`.
- Browser runtime - React UI served from `frontend/` and talking to the service API through `frontend/src/api.ts`.
- Optional native or containerized stack - `docker-compose.yml`, `Dockerfile.api`, and `Dockerfile.frontend` support local service/frontend boot.
- `uv` - Python dependency management and execution (`pyproject.toml`, `uv.lock`, `Makefile`).
- npm/Bun - Frontend and host-install tooling (`frontend/package.json`, `docker-compose.yml`, `src/atelier/infra/runtime/stack_lifecycle.py`).
- Lockfiles: `uv.lock` is committed; frontend install logic uses `npm ci` only when a lockfile exists, otherwise falls back to `npm install` (`src/atelier/infra/runtime/stack_lifecycle.py`, `scripts/install.sh`).

## Frameworks

- Click - CLI command surface in `src/atelier/gateway/cli/app.py`.
- FastAPI + Pydantic - HTTP service and request models in `src/atelier/core/service/api.py`, `src/atelier/core/service/auth.py`, and `src/atelier/core/service/schemas.py`.
- Custom MCP JSON-RPC server - tool registry and session/runtime plumbing in `src/atelier/gateway/adapters/mcp_server.py`.
- React 18 + React Router - frontend shell and navigation in `frontend/src/App.tsx`.
- pytest - backend/unit/integration suites configured in `pyproject.toml` and organized under `tests/`.
- Vitest + Testing Library + jsdom - frontend tests from `frontend/package.json` and files like `frontend/src/pages/Swarm.test.tsx`.
- CodeQL + pip-audit - CI security checks in `.github/workflows/tests.yml`.
- Ruff + Black + mypy - Python lint/format/typecheck in `Makefile`.
- Vite + TypeScript + Tailwind/PostCSS - frontend build chain in `frontend/package.json`.
- Docker Compose - local stack orchestration in `docker-compose.yml`.

## Key Dependencies

- `litellm` / `tiktoken` - model routing and token accounting (`pyproject.toml`, `src/atelier/core/capabilities/`).
- `tree-sitter` + `tree-sitter-language-pack` - semantic file memory and code intelligence (`pyproject.toml`, `src/atelier/infra/tree_sitter/`, `src/atelier/core/capabilities/code_context/engine.py`).
- `fastapi` + `uvicorn` - service surface (`pyproject.toml`, `src/atelier/core/service/api.py`).
- `sqlalchemy` + sqlite/postgres backends - storage abstraction (`pyproject.toml`, `src/atelier/infra/storage/factory.py`).
- `react`, `react-router-dom`, `posthog-js` - optional UI and telemetry (`frontend/package.json`, `frontend/src/App.tsx`).
- `GitPython` + `pygit2` - repository-aware operations and swarm/worktree flows (`pyproject.toml`, `src/atelier/infra/runtime/swarm_worktree.py`).
- `prometheus-client` + OpenTelemetry packages - metrics/export plumbing (`pyproject.toml`, `deploy/otel-collector.yaml`).
- Optional sidecars: `letta-client`, `openai`, `ollama`, `pgvector` via extras in `pyproject.toml`.

## Configuration

- `ATELIER_*` env vars drive runtime root, auth, storage backend, service host/port, memory backend, and telemetry (`src/atelier/core/service/config.py`, `.env.production.example`).
- Workspace-sensitive paths derive from `ATELIER_ROOT`, `ATELIER_WORKSPACE_ROOT`, `ATELIER_LESSONS_ROOT`, and host-specific cwd variables (`src/atelier/core/foundation/paths.py`).
- Python/project metadata: `pyproject.toml`.
- Automation targets: `Makefile`.
- Frontend build/test entrypoints: `frontend/package.json`, `frontend/scripts/run-vitest.mjs`.
- Host/runtime config surfaces: `src/atelier/gateway/hosts/configs/*.yaml`, `integrations/*`.

## Platform Requirements

- Cross-platform Python + uv workflow with Git available (`pyproject.toml`, `Makefile`, `scripts/install.sh`).
- Node/npm required for the optional frontend and some host installs; Bun is used by the dockerized frontend dev flow (`frontend/package.json`, `docker-compose.yml`).
- Optional Docker for the local stack and sidecars (`docker-compose.yml`, `deploy/`).
- Supports local user-level install under `~/.local/bin` plus background services (`README.md`, `scripts/install.sh`).
- Container-friendly deployment for service/frontend with env-based configuration (`Dockerfile.api`, `Dockerfile.frontend`, `.env.production.example`).
- Host integrations target macOS, Linux, and Windows via generated config packs (`src/atelier/gateway/hosts/configs/*.yaml`).
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- Python code uses `snake_case` for modules/functions and `PascalCase` for classes (`src/atelier/infra/storage/factory.py`, `src/atelier/gateway/hosts/registry.py`).
- React components/pages are `PascalCase` exports in `frontend/src/pages/*.tsx` and `frontend/src/components/*`.
- Environment variables and configuration flags are `ATELIER_*` throughout service/runtime/install code (`src/atelier/core/service/config.py`, `scripts/install.sh`).
- CLI commands are organized as module-per-command under `src/atelier/gateway/cli/commands/`.
- Tests follow `test_<surface>.py` in pytest and `*.test.tsx` for frontend interaction tests.

## Code Style

- Python targets 3.11+, uses strict mypy, Ruff, and Black (`pyproject.toml`, `Makefile`).
- Many Python modules start with `from __future__ import annotations` and explicit return types (`src/atelier/gateway/cli/app.py`, `src/atelier/core/runtime/engine.py`).
- Frontend code uses functional React components with hooks and typed interfaces (`frontend/src/App.tsx`, `frontend/src/api.ts`).
- Repository guidance explicitly says all Python commands should run through `uv run ...` (`CLAUDE.md`).

## Import Organization

- Python modules generally follow stdlib -> third-party -> local imports, often with `TYPE_CHECKING` blocks when needed (`src/atelier/infra/storage/factory.py`, `src/atelier/gateway/sdk/local.py`).
- Backend packages preserve the gateway/core/infra separation rather than reaching across layers ad hoc (`CLAUDE.md`, `src/atelier/` tree).
- Frontend imports group React/vendor imports first, then local pages/components/lib modules (`frontend/src/App.tsx`).

## Error Handling

- Core API/auth paths prefer explicit exceptions with actionable messages (`src/atelier/core/service/auth.py`, `src/atelier/infra/storage/factory.py`).
- Optional integrations often fail open and log instead of interrupting the main runtime (`src/atelier/gateway/integrations/langfuse.py`, `src/atelier/gateway/integrations/openmemory.py`).
- Service and remote-client code use framework-native status handling (`HTTPException`, typed unavailable exceptions, `ApiError` in `frontend/src/api.ts`).
- Security-sensitive comparisons use `secrets.compare_digest` instead of plain equality (`src/atelier/core/service/auth.py`).

## Logging

- Python modules typically define `logger = logging.getLogger(__name__)` and emit structured warnings/debug info (`src/atelier/gateway/adapters/mcp_server.py`, `src/atelier/gateway/integrations/langfuse.py`).
- Product telemetry events are emitted as a first-class cross-cutting concern from CLI/MCP/runtime code (`src/atelier/gateway/cli/app.py`, `src/atelier/core/service/telemetry/`).
- Shell/install flows print framed human-readable progress rather than raw command noise (`scripts/install.sh`).

## Comments

- Module docstrings are common and usually describe the surface contract or usage pattern (`src/atelier/gateway/adapters/runtime.py`, `src/atelier/core/service/api.py`).
- Inline comments are used sparingly for unusual behavior, invariants, or debt notes rather than narrating obvious code.
- Repository guidance discourages unnecessary comments and emphasizes small, surgical changes (`CLAUDE.md`).

## Function Design

- Helper-heavy modules often expose a small public surface and many private `_helper` functions (`src/atelier/core/foundation/paths.py`, `src/atelier/infra/runtime/stack_lifecycle.py`).
- Factories and adapters return typed abstractions (`make_memory_store`, `LocalClient`, `ContextRuntime`) instead of leaking backend wiring to callers.
- Frontend API calls centralize fetch/error behavior in `frontend/src/api.ts` rather than duplicating network logic across pages.

## Module Design

- Entry points stay thin: new behavior is expected in `core/capabilities/`, not in CLI/MCP shells (`CLAUDE.md`, `src/atelier/gateway/cli/app.py`).
- Generated host instruction assets are treated as distribution artifacts; `docs/agent-os/` is the source of truth (`CLAUDE.md`, `Makefile`, `scripts/sync_agent_context.py`).
- Host integrations isolate per-runtime differences in `integrations/` and `src/atelier/gateway/hosts/` rather than mixing them into core logic.
- Runtime state, lessons, and workspace-specific data are deliberately separated by path helpers (`src/atelier/core/foundation/paths.py`).
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## Pattern Overview

- One product exposes several entry surfaces: CLI, MCP server, HTTP API, SDK middleware, install scripts, and a browser dashboard.
- Domain behavior is capability-oriented inside `src/atelier/core/capabilities/`.
- Persistence, code-intel, embeddings, and sidecars are isolated under `src/atelier/infra/`.
- Host/plugin artifacts are generated or installed into `integrations/` from shared source material in `docs/agent-os/`.

## Layers

- Purpose: User/host-facing entry points and adapters.
- Contains: Click CLI, MCP server, host configs, SDK wrappers, external integrations.
- Location: `src/atelier/gateway/`.
- Depends on: `core` orchestration and `infra` implementations through runtime/storage abstractions.
- Purpose: Domain logic and product behavior.
- Contains: Capabilities, models, routing, rubrics, runtime orchestrator, service layer.
- Location: `src/atelier/core/`.
- Depends on: `infra` for concrete persistence/runtime utilities.
- Purpose: Concrete backends and process/runtime services.
- Contains: SQLite/Postgres stores, run ledgers, code-intel engines, sidecar bridges, embeddings.
- Location: `src/atelier/infra/`.
- Depends on: external libraries and OS/runtime services.
- Purpose: Visualization and installation surfaces.
- Contains: React UI, host integrations, install scripts, docs-site, Docker assets.
- Location: `frontend/`, `integrations/`, `scripts/`, `deploy/`.

## Data Flow

## Key Abstractions

- `ContextRuntime` (`src/atelier/gateway/adapters/runtime.py`) - main in-process host/runtime facade.
- `AtelierRuntimeCore` (`src/atelier/core/runtime/engine.py`) - capability orchestrator for context, routing, compression, proof gating, and tool supervision.
- `CodeContextEngine` (`src/atelier/core/capabilities/code_context/engine.py`) - large code-intel/index/query engine for symbols, routes, usages, and search packing.
- `RunLedger` / `RealtimeContextManager` (`src/atelier/infra/runtime/run_ledger.py`, `src/atelier/infra/runtime/realtime_context.py`) - persistent session/event tracking.
- `HostRegistry` (`src/atelier/gateway/hosts/registry.py`) - install-time host registration/fingerprinting.
- Swarm managers (`src/atelier/core/capabilities/swarm/capability.py`, `src/atelier/infra/runtime/swarm_worktree.py`) - parallel child-run orchestration and git worktree handling.

## Entry Points

- `src/atelier/gateway/cli/app.py`
- Trigger: `atelier ...`
- `src/atelier/gateway/adapters/mcp_server.py`
- Trigger: host MCP launch via `atelier mcp`
- `src/atelier/core/service/api.py`
- Trigger: FastAPI app / `atelier service start`
- `src/atelier/gateway/sdk/local.py`, `src/atelier/sdk/middleware.py`
- Trigger: embedding Atelier inside other agent runtimes
- `frontend/src/main.tsx`, `frontend/src/App.tsx`
- Trigger: Vite dev/build or Docker frontend service

## Error Handling

- Service auth raises `HTTPException` with precise status codes (`src/atelier/core/service/auth.py`).
- Storage/runtime factories raise explicit `ValueError`/unavailable exceptions on unsupported backends (`src/atelier/infra/storage/factory.py`, `src/atelier/infra/internal_llm/*.py`).
- Optional integrations often swallow/log exceptions to avoid taking down the core loop (`src/atelier/gateway/integrations/langfuse.py`, `src/atelier/gateway/integrations/openmemory.py`).

## Cross-Cutting Concerns

- Telemetry/session accounting begins in both CLI and MCP entrypoints (`src/atelier/gateway/cli/app.py`, `src/atelier/gateway/adapters/mcp_server.py`).
- Workspace/root resolution separates runtime state from git-tracked lessons (`src/atelier/core/foundation/paths.py`).
- Generated host instruction surfaces must stay in sync with `docs/agent-os/` (`CLAUDE.md`, `Makefile`, `scripts/sync_agent_context.py`).
- Swarm, install, and plugin flows couple filesystem, git, and subprocess behavior across multiple directories (`scripts/install.sh`, `src/atelier/core/capabilities/swarm/capability.py`, `integrations/claude/plugin/hooks/`).
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.

<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.

<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.

<!-- GSD:profile-end -->
