# External Integrations

**Analysis Date:** 2026-06-08

## APIs & External Services

**LLM Providers:**

- LiteLLM (gateway) - Unified multi-provider LLM access. `src/atelier/infra/internal_llm/litellm_client.py`, pricing in `src/atelier/core/capabilities/pricing.py`.
  - SDK/Client: `litellm>=1.83`
  - Model selection: `ATELIER_LLM_BACKEND`, `ATELIER_MODEL`, `ATELIER_LITELLM_MODEL`
- OpenAI - Direct client. `src/atelier/infra/internal_llm/openai_client.py`, embeddings `src/atelier/infra/embeddings/openai_embedder.py`.
  - SDK/Client: `openai>=1.0` (optional `cloud` extra)
  - Auth: `OPENAI_API_KEY` (standard SDK env var)
- Ollama (local models) - `src/atelier/infra/internal_llm/ollama_client.py`, embeddings `src/atelier/infra/embeddings/ollama_embedder.py`.
  - SDK/Client: `ollama>=0.4` (optional `smart` extra)
  - Config: `ATELIER_LOCAL_SLM_URL`, `ATELIER_LOCAL_SLM_MODEL`

**Code Intelligence (external binaries, subprocess-invoked):**


  - Bin override: `ATELIER_AST_GREP_BIN` and similar `*_BIN` env vars.
- ast-grep - Structural search/rewrite. `src/atelier/infra/code_intel/astgrep/`.
- Zoekt - Trigram code search (`zoekt-git-index`, `zoekt-webserver`, `zoekt-query`). `src/atelier/infra/code_intel/zoekt/`.

## Data Storage

**Databases:**

- SQLite (default) - `src/atelier/infra/storage/sqlite_store.py`, memory `sqlite_memory_store.py`. Selected by `ATELIER_STORAGE_BACKEND=sqlite`.
  - Local state under `~/.atelier/` (or `$ATELIER_ROOT`): run ledgers, session stats, savings events.
- PostgreSQL - `src/atelier/infra/storage/postgres_store.py`. Selected by `ATELIER_STORAGE_BACKEND=postgres`.
  - Client: `psycopg[binary]>=3.1` (optional `postgres` extra); SQLAlchemy >=2.0 toolkit.
  - Connection: `ATELIER_DATABASE_URL` (e.g. `postgresql://atelier:atelier@postgres:5432/atelier`)
- Backend factory: `src/atelier/infra/storage/factory.py` (raises if not sqlite/postgres).

**Vector / Embeddings:**

- pgvector - Vector similarity for Postgres (`pgvector>=0.2`, optional `vector` extra). `src/atelier/infra/storage/vector.py`.
- Embedding providers (factory `src/atelier/infra/embeddings/factory.py`): OpenAI, Ollama, Letta, local, null. Selected via `ATELIER_EMBEDDER` / `ATELIER_EMBEDDING_PROVIDER` / `ATELIER_EMBEDDING_MODEL` / `ATELIER_EMBEDDING_DIM`.

**File Storage:**

- Local filesystem under `~/.atelier/` workspaces. Artifacts in `artifacts/`, reports in `reports/`.

**Caching:**

- In-process / SQLite-backed context reuse; no external cache service (Redis etc.) detected. Toggle: `ATELIER_CACHE_DISABLED`.

## Authentication & Identity

**Service auth:**

- Custom Bearer token. `src/atelier/core/service/auth.py` — `verify_api_key()` FastAPI dependency.
  - `ATELIER_REQUIRE_AUTH=false` (local default) → all requests pass.
  - `ATELIER_REQUIRE_AUTH=true` → requires `Authorization: Bearer <ATELIER_API_KEY>`.
  - Config: `src/atelier/core/service/config.py` (`api_key` never exposed in `/config` summary).
- Team/workspace/invite/role endpoints (`/v1/team/*`) provide multi-user governance over the base service auth.

## Memory Bridges (external memory backends)

- Letta - `src/atelier/infra/memory_bridges/letta_adapter.py`. CLI `src/atelier/gateway/cli/commands/letta.py`.
  - SDK: `letta-client>=1.7` (`memory` extra) / `letta>=0.16` server (`memory-server` extra).
  - Config: `ATELIER_LETTA_URL`, `ATELIER_LETTA_API_KEY`. Deploy: `deploy/letta/docker-compose.yml` (port 8283).
  - OpenAPI spec vendored at `openapi_letta.json`.
- OpenMemory (MCP) - `src/atelier/infra/memory_bridges/openmemory.py`, lifecycle `src/atelier/gateway/integrations/openmemory_lifecycle.py`.
  - Config: `ATELIER_OPENMEMORY_MCP_SERVER_NAME`.
- Selection via `ATELIER_MEMORY_BACKEND` (sqlite / letta / openmemory).

## Monitoring & Observability

**Telemetry/Tracing:**

- OpenTelemetry - OTLP HTTP exporter (`opentelemetry-exporter-otlp-proto-http>=1.27`). `src/atelier/core/service/telemetry/exporters/otel.py`, config `telemetry/config.py`.
  - Endpoint: `ATELIER_OTEL_ENDPOINT` (e.g. `http://otel-collector:4318`). Collector configs: `deploy/otel-collector.yaml`, `deploy/otel-collector-dev.yaml`.
- PostHog - Product analytics. Frontend SDK `posthog-js` (`frontend/src/lib/telemetry.ts`, `insightsApi.ts`). Backend exporter `telemetry/exporters/posthog_frontend.py`. OTLP route `POSTHOG_OTLP_ENDPOINT` (default `https://us.i.posthog.com/i/v0/otlp`, `docker-compose.yml`).
- Langfuse - Optional LLM tracing, gated by `ATELIER_LANGFUSE_ENABLED`.

**Metrics:**

- Prometheus - `prometheus-client` instrumentation in `tool_supervision/capability.py`, `memory_arbitration/arbiter.py`, `telemetry/context_budget.py`.

**Local telemetry store:**

- `src/atelier/core/service/telemetry/local_store.py` + scrubber (`scrubber.py`) for PII redaction before export. Endpoints `/telemetry/*`.

## Agent Host Integrations

- MCP stdio server - `src/atelier/gateway/adapters/mcp_server.py` (entry `atelier mcp`). Tools: read/edit/search/symbols/callers/usages/impact/pattern/explore.
- Host adapters in `src/atelier/gateway/adapters/`: `aider_adapter.py`, `continue_adapter.py`, `cursor_adapter.py`, `hermes_adapter.py`, `langgraph_adapter.py`, `openhands_adapter.py`, `sweagent_adapter.py`, `remote_client.py`.
- Host instruction generation: `integrations/{claude,codex,copilot,cursor,opencode,hermes,antigravity}/` from shared partials (`make sync-agent-context`).

## CI/CD & Deployment

**Hosting:**

- Docker Compose (`docker-compose.yml`): `service` (FastAPI, port 8787) + `frontend` (Bun/Vite, port 3125). Frontend prod image: nginx:1.27-alpine (`Dockerfile.frontend`).

**CI Pipeline:**

- `.github/` workflows (GitHub Actions). Local git hooks in `.githooks/` (`pre-commit`, `pre-push`).
- Validation gates via `Makefile` (`make pre-commit`: format + lint + typecheck + docs + test).

## Version Control / Git

- GitPython + pygit2 used for repo introspection and history mining (`infra/code_intel/git_history`).
- `GITHUB_TOKEN` referenced in `.env.production.example` for lesson PR bot (`ATELIER_LESSON_PR_BOT_ENABLED`, default false). No direct GitHub API webhook handlers detected in `src/`.

## Webhooks & Callbacks

**Incoming:**

- None detected — service exposes a REST API (`/v1/*`), not webhook receivers.

**Outgoing:**

- OTLP telemetry exports (OpenTelemetry/PostHog endpoints).
- Optional lesson PR bot to GitHub (disabled by default).

## Environment Configuration

**Required env vars (production, `.env.production.example`):**

- `ATELIER_ROOT`, `ATELIER_WORKSPACE_ROOT`, `ATELIER_LESSONS_ROOT`
- `ATELIER_STORAGE_BACKEND=postgres`, `ATELIER_DATABASE_URL`
- `ATELIER_SERVICE_ENABLED`, `ATELIER_SERVICE_URL`, `ATELIER_REQUIRE_AUTH=true`, `ATELIER_API_KEY`
- `ATELIER_MCP_MODE=remote`, `ATELIER_OPENMEMORY_MCP_SERVER_NAME`
- `GITHUB_TOKEN` (optional), `ATELIER_LETTA_URL` (optional)

**Secrets location:**

- Env vars only; `.env*` files gitignored. No secrets committed. Service `/config` endpoint never returns the API key value (`core/service/config.py`).

---

_Integration audit: 2026-06-08_
