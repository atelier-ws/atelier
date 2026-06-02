# Technology Stack

**Analysis Date:** 2026-06-02

## Languages

**Primary:**
- Python >=3.11 - Core runtime, CLI, MCP server, HTTP service, host integrations, and most benchmarks live under `src/atelier/`, `src/benchmarks/`, `scripts/`, and `tests/`.

**Secondary:**
- TypeScript 5.5.3 - Optional React frontend in `frontend/src/`.
- Bash - Install/bootstrap and verification flows in `scripts/install.sh`, `scripts/install_claude.sh`, and `scripts/verify_*.sh`.
- YAML / JSON / Markdown - Host configs in `src/atelier/gateway/hosts/configs/*.yaml`, workflow docs under `docs/`, and generated agent surfaces in `integrations/`.

## Runtime

**Environment:**
- Python/uv runtime - `pyproject.toml` and `uv.lock` drive the backend environment; repository guidance requires `uv run ...`.
- Browser runtime - React UI served from `frontend/` and talking to the service API through `frontend/src/api.ts`.
- Optional native or containerized stack - `docker-compose.yml`, `Dockerfile.api`, and `Dockerfile.frontend` support local service/frontend boot.

**Package Manager:**
- `uv` - Python dependency management and execution (`pyproject.toml`, `uv.lock`, `Makefile`).
- npm/Bun - Frontend and host-install tooling (`frontend/package.json`, `docker-compose.yml`, `src/atelier/infra/runtime/stack_lifecycle.py`).
- Lockfiles: `uv.lock` is committed; frontend install logic uses `npm ci` only when a lockfile exists, otherwise falls back to `npm install` (`src/atelier/infra/runtime/stack_lifecycle.py`, `scripts/install.sh`).

## Frameworks

**Core:**
- Click - CLI command surface in `src/atelier/gateway/cli/app.py`.
- FastAPI + Pydantic - HTTP service and request models in `src/atelier/core/service/api.py`, `src/atelier/core/service/auth.py`, and `src/atelier/core/service/schemas.py`.
- Custom MCP JSON-RPC server - tool registry and session/runtime plumbing in `src/atelier/gateway/adapters/mcp_server.py`.
- React 18 + React Router - frontend shell and navigation in `frontend/src/App.tsx`.

**Testing:**
- pytest - backend/unit/integration suites configured in `pyproject.toml` and organized under `tests/`.
- Vitest + Testing Library + jsdom - frontend tests from `frontend/package.json` and files like `frontend/src/pages/Swarm.test.tsx`.
- CodeQL + pip-audit - CI security checks in `.github/workflows/tests.yml`.

**Build/Dev:**
- Ruff + Black + mypy - Python lint/format/typecheck in `Makefile`.
- Vite + TypeScript + Tailwind/PostCSS - frontend build chain in `frontend/package.json`.
- Docker Compose - local stack orchestration in `docker-compose.yml`.

## Key Dependencies

**Critical:**
- `litellm` / `tiktoken` - model routing and token accounting (`pyproject.toml`, `src/atelier/core/capabilities/`).
- `tree-sitter` + `tree-sitter-language-pack` - semantic file memory and code intelligence (`pyproject.toml`, `src/atelier/infra/tree_sitter/`, `src/atelier/core/capabilities/code_context/engine.py`).
- `fastapi` + `uvicorn` - service surface (`pyproject.toml`, `src/atelier/core/service/api.py`).
- `sqlalchemy` + sqlite/postgres backends - storage abstraction (`pyproject.toml`, `src/atelier/infra/storage/factory.py`).
- `react`, `react-router-dom`, `posthog-js` - optional UI and telemetry (`frontend/package.json`, `frontend/src/App.tsx`).

**Infrastructure:**
- `GitPython` + `pygit2` - repository-aware operations and swarm/worktree flows (`pyproject.toml`, `src/atelier/infra/runtime/swarm_worktree.py`).
- `prometheus-client` + OpenTelemetry packages - metrics/export plumbing (`pyproject.toml`, `deploy/otel-collector.yaml`).
- Optional sidecars: `letta-client`, `openai`, `ollama`, `pgvector` via extras in `pyproject.toml`.

## Configuration

**Environment:**
- `ATELIER_*` env vars drive runtime root, auth, storage backend, service host/port, memory backend, and telemetry (`src/atelier/core/service/config.py`, `.env.production.example`).
- Workspace-sensitive paths derive from `ATELIER_ROOT`, `ATELIER_WORKSPACE_ROOT`, `ATELIER_LESSONS_ROOT`, and host-specific cwd variables (`src/atelier/core/foundation/paths.py`).

**Build:**
- Python/project metadata: `pyproject.toml`.
- Automation targets: `Makefile`.
- Frontend build/test entrypoints: `frontend/package.json`, `frontend/scripts/run-vitest.mjs`.
- Host/runtime config surfaces: `src/atelier/gateway/hosts/configs/*.yaml`, `integrations/*`.

## Platform Requirements

**Development:**
- Cross-platform Python + uv workflow with Git available (`pyproject.toml`, `Makefile`, `scripts/install.sh`).
- Node/npm required for the optional frontend and some host installs; Bun is used by the dockerized frontend dev flow (`frontend/package.json`, `docker-compose.yml`).
- Optional Docker for the local stack and sidecars (`docker-compose.yml`, `deploy/`).

**Production:**
- Supports local user-level install under `~/.local/bin` plus background services (`README.md`, `scripts/install.sh`).
- Container-friendly deployment for service/frontend with env-based configuration (`Dockerfile.api`, `Dockerfile.frontend`, `.env.production.example`).
- Host integrations target macOS, Linux, and Windows via generated config packs (`src/atelier/gateway/hosts/configs/*.yaml`).

---

*Stack analysis: 2026-06-02*
*Update after major dependency changes*
