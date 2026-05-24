# Technology Stack

**Analysis Date:** 2025-01-27

## Languages & Runtimes

**Primary:**
- Python 3.11+ (required minimum), tested on 3.12/3.13 — all backend/runtime/agent code in `src/atelier/`
- TypeScript 5.5 — frontend dashboard in `frontend/src/`

**Secondary:**
- YAML — configuration files, rubric definitions, OTel collector config in `deploy/`
- TOML — project config (`pyproject.toml`), telemetry config (`~/.atelier/telemetry.toml`)

## Runtime

**Backend Environment:**
- Python 3.11+ (CPython)
- Package manager: **uv** (Astral) — `uv.lock` lockfile committed; `uv run` used for all commands

**Frontend Environment:**
- Node.js (npm/bun) — Bun 1.x used in Docker compose dev mode (`oven/bun:1` image)
- Runtime port: 3125

**Package Manager:**
- Backend: `uv` — `uv.lock` present and committed
- Frontend: bun (dev/Docker) / npm (CI) — `frontend/package.json`

## Frameworks

**Core Backend:**
- **FastAPI** `>=0.136.1` — HTTP service API (`src/atelier/core/service/api.py`)
- **Uvicorn** `>=0.46.0` (with `[standard]` extras) — ASGI server
- **Pydantic v2** `>=2.6` — data validation/models throughout `src/atelier/core/foundation/`
- **Pydantic-settings** `>=2.14.0` — environment-based configuration
- **Click** `>=8.1` — CLI framework (`src/atelier/gateway/adapters/cli.py`)
- **Rich** `>=13.7` — terminal formatting / CLI output

**Frontend:**
- **React 18** — UI components in `frontend/src/`
- **Vite 5** — build tool and dev server
- **React Router 6** — client-side routing
- **TailwindCSS 3** — utility-first CSS framework
- **react-markdown** `^10.1.0` — markdown rendering in UI

**Testing:**
- Backend: **pytest** `>=9.0.3` with `pytest-cov`, `pytest-xdist` (parallel test runs)
- Frontend: **Vitest** `^2.1.5` with `@testing-library/react`

## Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `litellm` | `>=1.83.14` | LLM gateway — unified API across all LLM providers |
| `ollama` | `>=0.6.2` | Local Ollama LLM client for internal background processing |
| `openai` | `>=1.0` (optional `[cloud]`) | OpenAI-compatible LLM access (OpenAI, OpenRouter, vllm) |
| `pydantic` | `>=2.6` | Data models, validation throughout |
| `sqlalchemy` | `>=2.0.49` | ORM for SQLite and Postgres storage |
| `fastapi` | `>=0.136.1` | HTTP REST API service |
| `tiktoken` | `>=0.9` | Token counting for context budget management |
| `tree-sitter` | `>=0.23` | Code parsing/AST analysis in `src/atelier/infra/tree_sitter/` |
| `tree-sitter-language-pack` | `>=1.8.1` | Language grammars bundle |
| `GitPython` | `>=3.1.50` | Git repository interaction |
| `pygit2` | `==1.19.2` | Low-level libgit2 bindings (pinned exact version) |
| `networkx` | `>=3.4` | Graph-based repo dependency analysis |
| `datasketch` | `>=1.6` | MinHash/LSH for similarity hashing |
| `blake3` | `>=0.4.1` | Fast cryptographic hashing for content IDs |
| `prometheus-client` | `>=0.21` | Metrics exposition endpoint |
| `opentelemetry-api/sdk` | `>=1.27` | Distributed tracing instrumentation |
| `opentelemetry-exporter-otlp-proto-http` | `>=1.27` | OTLP HTTP export to collector |
| `tenacity` | `>=9.0` | Retry logic |
| `pybreaker` | `>=1.2` | Circuit breaker pattern |
| `river` | `>=0.22` | Online machine learning (adaptive token budgeting) |
| `ortools` | `>=9.10` | Operations Research / optimization (context packing) |
| `mcp` | `>=1.0` (optional `[mcp]`) | Model Context Protocol SDK (MCP server) |
| `letta-client` | `>=1.7.12` (optional `[memory]`) | Letta/MemGPT memory sidecar client |
| `letta` | `>=0.16.7` (optional `[memory-server]`) | Self-hosted Letta server |
| `psycopg` | `>=3.1` (optional `[postgres]`) | PostgreSQL driver (psycopg v3) |
| `pgvector` | `>=0.2` (optional `[vector]`) | pgvector extension client |
| `numpy` | `>=1.26` (optional `[vector]`) | Numerical arrays for vector operations |
| `rope` | `>=0.23` (optional `[rename]`) | Python refactoring/rename support |
| `diff-match-patch` | `>=2.1` | Diff/patch operations for code edits |
| `mypy` | `>=1.20.2` | Static type checking (in core deps, not just dev) |
| `posthog-js` | `^1.150.0` (frontend) | Product analytics in browser |

## Build & Tooling

**Python Build System:**
- **Hatchling** — `[build-system]` backend in `pyproject.toml`
- `hatch.build.targets.wheel` configured to bundle `seed_blocks`, `rubrics`, `frustration_lexicon.yaml`, and `templates/reasonblocks` as package data

**Linting / Formatting:**
- **Ruff** `>=0.5` — linting (`E`, `F`, `I`, `B`, `UP`, `SIM`, `RUF` rules), line-length 100
- **Black** `>=24.4` — code formatting, line-length 120, target `py311`
- **mypy** `>=1.10` — strict type checking

**Frontend Build:**
- **Vite** with `@vitejs/plugin-react`
- **TypeScript** `^5.5.3` with strict compilation
- **PostCSS** + **autoprefixer** for CSS processing
- **Prettier** for formatting (invoked via `npx prettier` in `make format`)

**Container / Deployment:**
- **Docker** — `Dockerfile.api` (Python 3.12-slim + uv) on port 8787; `Dockerfile.frontend` (Bun)
- **Docker Compose** — `docker-compose.yml` orchestrates `service` (8787) + `frontend` (3125) + optional `otel-collector` (4318)

**Task Runner:**
- **GNU Make** — `Makefile` at repo root; primary developer interface

## Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Python project manifest, dependencies, tool config (ruff, black, pytest, mypy) |
| `uv.lock` | Locked dependency graph for uv |
| `frontend/package.json` | Frontend JS dependencies and scripts |
| `docker-compose.yml` | Multi-service Docker orchestration |
| `Dockerfile.api` | Python API service container (python:3.12-slim + uv) |
| `Dockerfile.frontend` | Frontend container |
| `deploy/otel-collector.yaml` | Production OTel collector (OTLP→PostHog + GCP) |
| `deploy/otel-collector-dev.yaml` | Dev OTel collector config |
| `~/.atelier/telemetry.toml` | User-level telemetry opt-out config (runtime, not committed) |
| `.env.worktree` | Per-worktree local env overrides (runtime, not committed) |

## Platform Requirements

**Development:**
- Python 3.11+ (3.12 or 3.13 recommended)
- `uv` package manager
- Node.js / bun (for frontend only)
- Optional: Docker + Docker Compose for containerized dev

**Production (Containerized):**
- Docker (python:3.12-slim base for API, oven/bun:1 for frontend)
- Exposed: port 8787 (API), port 3125 (frontend)
- Optional: OpenTelemetry collector on port 4318

**OS-level Services:**
- systemd (Linux) or launchd (macOS) — Atelier registers itself as a boot-time background service (`atelier background ...`)

---

*Stack analysis: 2025-01-27*
