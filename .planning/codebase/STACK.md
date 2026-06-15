# Technology Stack

**Analysis Date:** 2026-06-08

## Languages

**Primary:**
- Python 3.12+ - All backend/runtime code in `src/atelier/` (gateway, core, infra layers), benchmarks, scripts. `requires-python = ">=3.12"` in `pyproject.toml`.
- TypeScript 5.5 - Frontend SPA in `frontend/src/` (React app, `tsconfig.json`).

**Secondary:**
- YAML - Config and data (`frustration_lexicon.yaml`, `docker-compose.yml`, `deploy/*.yaml`, playbook templates).
- Shell - Git hooks (`.githooks/pre-commit`, `.githooks/pre-push`), installer scripts (`scripts/install_claude.sh`).

## Runtime

**Environment:**
- Python 3.12 (CPython) - Production container `Dockerfile.api` uses `python:3.12-slim`. Note: local dev machine observed running Python 3.13 (`__pycache__` shows `cpython-313`), but the project targets 3.12.
- Node.js / Bun - Frontend. Dev container uses `oven/bun:1` (`docker-compose.yml`); local Node observed at v24.12.0. Vite dev server on port 3125.

**Package Manager:**
- `uv` (Astral) - Python dependency management. Workspace config in `pyproject.toml` (`[tool.uv]`, members `benchmarks`, `integrations`).
  - Lockfile: `uv.lock` present (~1.2 MB, frozen installs via `uv sync --frozen`).
  - **All Python commands must run via `uv run`** — no activated venv (`CLAUDE.md`).
- `bun` (primary) / `npm` - Frontend. Lockfiles: `frontend/bun.lock` and `frontend/package-lock.json` both present.

## Frameworks

**Core (backend):**
- FastAPI >=0.136 - HTTP service surface (`src/atelier/core/service/api.py`). ~40 routes under `/v1/*`, `/telemetry/*`, `/analytics/*`.
- Uvicorn[standard] >=0.46 - ASGI server (`atelier service start`, port 8787).
- Pydantic >=2.6 - Domain models throughout `core/foundation/`.
- Click >=8.1 - CLI framework (`src/atelier/gateway/cli`, entry points `atelier`/`atl`).
- SQLAlchemy >=2.0 - DB toolkit for storage layer.
- MCP >=1.0 (optional `mcp` extra) - Model Context Protocol stdio server (`gateway/adapters/mcp_server.py`).

**Core (frontend):**
- React 18.3 + react-dom 18.3 - SPA.
- react-router-dom 6.26 - Routing.
- react-markdown 10.1 - Markdown rendering.
- lucide-react 1.16 - Icons.
- Tailwind CSS 3.4 + PostCSS 8.4 + autoprefixer - Styling (`frontend/tailwind.config.ts`, `postcss.config.js`).

**Testing:**
- pytest >=9.0 - Python tests (`tests/`, config in `[tool.pytest.ini_options]`). Plugins: pytest-cov, pytest-forked, pytest-timeout, pytest-xdist.
- Vitest 2.1 + @testing-library/react 16 + jsdom 25 - Frontend tests (`frontend/scripts/run-vitest.mjs`).

**Build/Dev:**
- Hatchling - Python build backend (`[build-system]`, wheel packages `src/atelier`, `src/benchmarks`).
- Vite 5.4 + @vitejs/plugin-react 4.3 - Frontend bundler (`frontend/vite.config.ts`).
- Ruff >=0.5 - Lint + import sort (`[tool.ruff]`, line-length 100, target py312, rules E/F/I/B/BLE/UP/RUF).
- Black >=24.4 - Formatter (line-length 120, py312).
- mypy >=1.20.2 - Strict type checking (`[tool.mypy]` strict=true, per-module overrides).

## Key Dependencies

**Critical:**
- litellm >=1.83 - Unified LLM gateway (`infra/internal_llm/litellm_client.py`, `core/capabilities/pricing.py`). Routing across model providers.
- tiktoken >=0.9 - Token counting.
- tree-sitter >=0.23 + tree-sitter-language-pack >=1.8 - Source parsing for code-intel.
- networkx >=3.4 - Graph algorithms (repo-map PageRank, capability registry graph).
- ortools >=9.10 - Constraint solver for budget optimizer (`core/capabilities/budget_optimizer/optimizer.py`).
- river >=0.22 - Online/streaming statistics (`core/capabilities/context_reuse`).
- pydantic-settings >=2.14 - Settings (though config modules largely use `os.environ` directly, see `core/service/config.py`).

**Infrastructure:**
- GitPython >=3.1.50 + pygit2 ==1.19.2 - Git operations and history mining (`infra/code_intel/git_history`).
- blake3 >=0.4 - Content hashing.
- datasketch >=1.6 - MinHash/LSH similarity.
- tenacity >=9.0 - Retry logic (`tool_supervision/capability.py`).
- pybreaker >=1.2 - Circuit breaker (`tool_supervision/capability.py`).
- prometheus-client >=0.21 - Metrics (`tool_supervision`, `memory_arbitration`, `telemetry/context_budget`).
- OpenTelemetry API/SDK + OTLP HTTP exporter >=1.27 - Tracing/telemetry export.
- beautifulsoup4, markdownify, trafilatura, lxml - HTML extraction/web content tooling.
- diff-match-patch >=2.1 - Text diffing.
- pexpect >=4.9 - Interactive subprocess control.
- posthog-js ^1.150 (frontend) - Product analytics.

## Configuration

**Environment:**
- Heavily env-var driven via `ATELIER_*` prefix (60+ variables). Read directly from `os.environ` in `core/service/config.py`, `core/environment.py`, capability `config.py` modules.
- `.env.production.example` documents production vars (storage backend, DB URL, auth, MCP mode). `.env*` files are gitignored; never committed with real secrets.
- Frontend uses Vite `import.meta.env` (`VITE_API_URL`, default `http://atelier-service:8787`).

**Key configs required:**
- `ATELIER_ROOT` - Runtime state dir (default `~/.atelier`).
- `ATELIER_STORAGE_BACKEND` - `sqlite` (default) or `postgres`.
- `ATELIER_DATABASE_URL` - Postgres DSN when backend=postgres.
- `ATELIER_REQUIRE_AUTH` / `ATELIER_API_KEY` - Service Bearer auth.
- `ATELIER_LLM_BACKEND`, `ATELIER_MODEL`, `ATELIER_LITELLM_MODEL` - LLM routing.
- `ATELIER_EMBEDDER` / `ATELIER_EMBEDDING_PROVIDER` - Embedding provider selection.

**Build:**
- `pyproject.toml` - Python project, deps, optional extras, tool configs.
- `frontend/tsconfig.json`, `tsconfig.node.json`, `vite.config.ts` - Frontend build.
- `Makefile` - Orchestrates lint/format/typecheck/test/docs gates.
- `Dockerfile.api` (Python service), `Dockerfile.frontend` (Bun build → nginx:1.27-alpine).

## Optional Extras (`pyproject.toml [project.optional-dependencies]`)

- `mcp` - MCP server (mcp>=1.0)
- `memory` / `memory-server` - Letta client / Letta server (letta-client, letta)
- `smart` - Ollama local models (ollama>=0.4)
- `cloud` - OpenAI SDK (openai>=1.0)
- `postgres` - psycopg[binary]>=3.1
- `vector` - pgvector>=0.2, numpy>=1.26
- `parsers` / `repo-map` - tree-sitter language grammars
- `rename` - rope>=0.23 (Python refactoring)
- `telemetry` - OpenTelemetry stack

## Platform Requirements

**Development:**
- Python 3.12 + `uv`; Node/Bun for frontend.
- External code-intel binaries (bundled/invoked, not pip deps): `scip-python`, `scip-typescript`, `scip-go`, `scip-java`, `scip-ruby`, `scip-clang`, `ast-grep`, `zoekt`/`zoekt-git-index`/`zoekt-webserver`. See `infra/code_intel/scip`, `astgrep`, `zoekt`.

**Production:**
- Docker Compose stack (`docker-compose.yml`): `service` (FastAPI on 8787) + `frontend` (Bun/Vite on 3125), optional otel-collector (commented).
- Postgres + pgvector for multi-user/persistent backend.
- Optional Letta memory server (`deploy/letta/docker-compose.yml`, image `letta/letta:latest`, port 8283).

---

*Stack analysis: 2026-06-08*
