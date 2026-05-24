# External Integrations

**Analysis Date:** 2025-01-27

## LLM Providers

Atelier uses a **two-tier LLM architecture**: `litellm` (gateway/unified) for rubric and capability calls, and a swappable internal backend (`ATELIER_LLM_BACKEND`) for lightweight background processing.

### Unified LLM Gateway — LiteLLM
- **Package:** `litellm>=1.83.14`
- **Purpose:** Unified interface for routing LLM calls to any provider (OpenAI, Anthropic, Gemini, Cohere, etc.)
- **Usage:** Core capability and rubric evaluation paths
- **Config:** Provider API keys are passed through from environment (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)

### Internal Background LLM (`src/atelier/infra/internal_llm/`)

Swappable via `ATELIER_LLM_BACKEND` env var:

| Backend | Env Value | Client File | Default |
|---------|-----------|-------------|---------|
| Ollama (local) | `ollama` | `src/atelier/infra/internal_llm/ollama_client.py` | ✅ Yes |
| OpenAI-compatible | `openai` or `openai_compatible` | `src/atelier/infra/internal_llm/openai_client.py` | No |

**Ollama client:**
- **Package:** `ollama>=0.6.2`
- Connects to local Ollama server
- Raises `OllamaUnavailable` when server is not running

**OpenAI-compatible client (`src/atelier/infra/internal_llm/openai_client.py`):**
- **Package:** `openai>=1.0` (optional, install with `atelier[cloud]`)
- Supports OpenAI directly, OpenRouter (`https://openrouter.ai/api/v1`), any local OpenAI-compatible server (vllm, llama.cpp, opencode)
- Config env vars:
  - `ATELIER_LLM_BACKEND=openai`
  - `ATELIER_OPENAI_BASE_URL` — custom base URL
  - `ATELIER_OPENAI_API_KEY` (falls back to `OPENAI_API_KEY`)
  - `ATELIER_OPENAI_MODEL` (default: `gpt-4o-mini`)

## Agent Framework Adapters

All adapters live in `src/atelier/gateway/adapters/` and extend `AgentAdapter` from `src/atelier/gateway/adapters/adapter_base.py`.

### MCP (Model Context Protocol) Server
- **File:** `src/atelier/gateway/adapters/mcp_server.py`
- **Package:** `mcp>=1.0` (optional, install with `atelier[mcp]`)
- **Protocol:** JSON-RPC over stdio (PROTOCOL_VERSION `2024-11-05`)
- **Entry point:** `atelier-mcp` CLI command
- **Hosts:** Claude Code, Codex (OpenAI), any MCP-compatible agent host
- **Tools exposed:** `context`, `trace`, `memory`, `read`, `grep`, `search`, `compact`, `route`, `edit`, `sql`, `shell`, `code` (stable); `rescue`, `verify` (dev-only, gated by `ATELIER_DEV_MODE=1`)

### LangGraph Adapter
- **File:** `src/atelier/gateway/adapters/langgraph_adapter.py`
- **Purpose:** Middleware for LangGraph graphs — wraps Atelier calls at node boundaries
- **Key methods:** `node_context()`, `node_pre_check()`, `edge_rubric_gate()`, `node_failure_recovery()`
- **Modes:** `shadow` | `suggest` | `enforce`

### CLI Adapter
- **File:** `src/atelier/gateway/adapters/cli.py`
- **Entry point:** `atelier` CLI command
- **Framework:** Click `>=8.1`

### Agent Host Adapters (in `src/atelier/gateway/adapters/`)
| Adapter File | Target Host |
|-------------|-------------|
| `aider_adapter.py` | Aider (AI pair programmer) |
| `continue_adapter.py` | Continue.dev (VS Code extension) |
| `openhands_adapter.py` | OpenHands (open-source devin) |
| `sweagent_adapter.py` | SWE-agent |
| `remote_client.py` | Remote HTTP client for detached service |

### Host Integrations (`integrations/`)
Atelier provides pre-built skill bundles and instruction files for major agent hosts:
- `integrations/claude/` — Claude Code (AGENTS.atelier.md, hooks, tasks, plugin)
- `integrations/codex/` — OpenAI Codex (AGENTS.atelier.md, hooks, plugin)
- `integrations/copilot/` — GitHub Copilot
- `integrations/opencode/` — opencode agent
- `integrations/antigravity/` — Antigravity agent host
- `integrations/skills/` — Shared skill definitions (`context`, `trace`, `rescue`, `savings`, etc.)

## MCP Integration

Atelier exposes itself as an MCP server via `atelier-mcp`:

**Protocol:** Model Context Protocol 2024-11-05, JSON-RPC over stdio

**Tool visibility rules** (`src/atelier/core/environment.py`):
- Stable tools (always visible): `compact`, `context`, `trace`, `memory`, `read`, `grep`, `search`, `route`, `edit`, `sql`, `shell`, `code`
- Dev-only tools (require `ATELIER_DEV_MODE=1`): `rescue`, `verify`

**Context window management:**
- Token budget: 200,000 tokens (`CONTEXT_WINDOW_TOKENS`)
- Compact advisory at 60% utilization
- Auto-compact at 80% utilization  
- Handover threshold at 95% utilization
- Auto-compact requires minimum 15 turns (bypassed if utilization exceeds threshold on fewer turns)

## Storage & Persistence

### Primary Data Store (Session/Ledger/Trace)

Configured via `ATELIER_STORAGE_BACKEND` env var. Factory: `src/atelier/infra/storage/factory.py`.

| Backend | Value | Class | Notes |
|---------|-------|-------|-------|
| SQLite | `sqlite` (default) | `src/atelier/infra/storage/sqlite_store.py` | File at `~/.atelier/` |
| PostgreSQL | `postgres` | `src/atelier/infra/storage/postgres_store.py` | Requires `atelier[postgres]`; 15 production tables |

- **SQLAlchemy** `>=2.0.49` — ORM layer for both backends
- **psycopg v3** `>=3.1` (optional, `atelier[postgres]`) — PostgreSQL driver
- **Connection:** `ATELIER_DATABASE_URL` env var for Postgres

### Memory Store (Archival / MemoryBlocks)

Configured via `ATELIER_MEMORY_BACKEND` env var. Factory: `src/atelier/infra/storage/factory.py` → `make_memory_store()`.

| Backend | Value | Class | Notes |
|---------|-------|-------|-------|
| SQLite | `sqlite` (default) | `src/atelier/infra/storage/sqlite_memory_store.py` | Local file |
| Letta | `letta` | `src/atelier/infra/memory_bridges/letta_adapter.py` | Requires `atelier[memory]` |
| OpenMemory | `openmemory` | `src/atelier/infra/memory_bridges/openmemory.py` | HTTP REST bridge |

### Vector Store
- **pgvector** `>=0.2` (optional, `atelier[vector]`) — vector similarity search in Postgres
- **numpy** `>=1.26` (optional, `atelier[vector]`) — array operations
- **Local fallback:** `src/atelier/infra/storage/vector.py` — deterministic feature-hashing embedder (384-dim, no ML model required)

### Embeddings (`src/atelier/infra/embeddings/`)

Configured via `ATELIER_EMBEDDER` env var. Factory: `src/atelier/infra/embeddings/factory.py`.

| Backend | Value | Class | Notes |
|---------|-------|-------|-------|
| Local (default) | `local` | `src/atelier/infra/embeddings/local.py` | Deterministic feature hashing, no network |
| OpenAI | `openai` | `src/atelier/infra/embeddings/openai_embedder.py` | Requires `OPENAI_API_KEY` |
| Letta | `letta` | `src/atelier/infra/embeddings/letta_embedder.py` | Via Letta sidecar |
| Null | `null` | `src/atelier/infra/embeddings/null_embedder.py` | No-op, for testing |

## Memory Sidecars

### Letta / MemGPT
- **Package:** `letta-client>=1.7.12` (install with `atelier[memory]`)
- **Self-hosted server:** `letta>=0.16.7` (install with `atelier[memory-server]`)
- **Adapter:** `src/atelier/infra/memory_bridges/letta_adapter.py`
- **Purpose:** Persistent archival memory via Letta's hosted memory service
- **Config:** Letta client auto-discovers local server or uses `LETTA_BASE_URL`
- **Deploy config:** `deploy/letta/` directory

### OpenMemory
- **Adapter:** `src/atelier/infra/memory_bridges/openmemory.py`
- **Bridge:** `src/atelier/gateway/integrations/openmemory.py`
- **Purpose:** REST-based memory sidecar (HTTP bridge to OpenMemory service)
- **Config:** `OPENMEMORY_BASE_URL` env var

## Observability & Telemetry

### OpenTelemetry (Distributed Tracing)
- **Packages:** `opentelemetry-api>=1.27`, `opentelemetry-sdk>=1.27`, `opentelemetry-exporter-otlp-proto-http>=1.27`
- **Exporter:** `src/atelier/core/service/telemetry/exporters/otel.py`
- **Collector config:** `deploy/otel-collector.yaml` (production), `deploy/otel-collector-dev.yaml`
- **Endpoint:** `ATELIER_OTEL_ENDPOINT` env var (default: `http://otel-collector:4318`)
- **Scrubbing:** PII fields (`cwd`, `file_path`, `repo_url`, `prompt`, `code`) stripped at collector

### PostHog (Product Analytics)
- **Backend:** OTLP pipeline via OTel collector → PostHog OTLP endpoint
- **Frontend:** `posthog-js ^1.150.0` in `frontend/src/lib/telemetry.ts`
- **Config:** `POSTHOG_OTLP_ENDPOINT`, `POSTHOG_PROJECT_API_KEY` (OTel collector env vars)
- **Opt-out:** `ATELIER_TELEMETRY=0` or `atelier telemetry off`; config in `~/.atelier/telemetry.toml`

### Google Cloud Logging
- **Exporter:** `googlecloud` in OTel collector config
- **Config:** `GCP_PROJECT_ID` env var
- **Log name:** `atelier`

### Prometheus
- **Package:** `prometheus-client>=0.21`
- **Purpose:** Metrics exposition

### Langfuse (Optional Trace Observability)
- **File:** `src/atelier/gateway/integrations/langfuse.py`
- **Package:** `langfuse` (optional, not in default deps — fail-open if missing)
- **Config:** `ATELIER_LANGFUSE_ENABLED=true`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (defaults to cloud)
- **Design:** Fail-open — any Langfuse error is silently swallowed

## Code Intelligence

### Tree-sitter (Code Parsing)
- **Package:** `tree-sitter>=0.23`, `tree-sitter-language-pack>=1.8.1`
- **Location:** `src/atelier/infra/tree_sitter/`
- **Purpose:** AST parsing for repo mapping, code intelligence, context extraction

### Git Integration
- **GitPython** `>=3.1.50` — high-level Git operations
- **pygit2** `==1.19.2` (pinned) — low-level libgit2 bindings
- **Location:** Used throughout `src/atelier/infra/code_intel/`

### External Analyzers (`src/atelier/gateway/integrations/external_analytics.py`)
Optional external CLI tools invoked as sidecars (fail-open design):
- **Tokscale** — token scaling analysis (env: `ATELIER_TOKSCALE_BIN`)

## External APIs

### REST Service API (self-hosted)
- **Framework:** FastAPI + Uvicorn
- **File:** `src/atelier/core/service/api.py`
- **Port:** 8787 (configurable via `ATELIER_SERVICE_PORT`)
- **Auth:** Optional Bearer token (`ATELIER_REQUIRE_AUTH`, `ATELIER_API_KEY`)
- **Health check:** `GET /health`

### Environment Variables Reference

| Variable | Purpose | Required |
|----------|---------|----------|
| `ATELIER_DEV_MODE` | Enable dev-only tools (`rescue`, `verify`) | No |
| `ATELIER_STORAGE_BACKEND` | `sqlite` (default) or `postgres` | No |
| `ATELIER_DATABASE_URL` | PostgreSQL connection string | If postgres |
| `ATELIER_MEMORY_BACKEND` | `sqlite`, `letta`, or `openmemory` | No |
| `ATELIER_EMBEDDER` | `local`, `openai`, `letta`, or `null` | No |
| `ATELIER_LLM_BACKEND` | `ollama` (default) or `openai` | No |
| `ATELIER_OPENAI_BASE_URL` | Custom OpenAI-compatible base URL | No |
| `ATELIER_OPENAI_API_KEY` | API key (falls back to `OPENAI_API_KEY`) | If openai backend |
| `ATELIER_OPENAI_MODEL` | Model name (default: `gpt-4o-mini`) | No |
| `OPENAI_API_KEY` | OpenAI API key (also used by LiteLLM) | If using OpenAI |
| `ATELIER_OTEL_ENDPOINT` | OTLP collector endpoint | No |
| `ATELIER_TELEMETRY` | `0`/`false` to disable telemetry | No |
| `ATELIER_LANGFUSE_ENABLED` | `true` to enable Langfuse export | No |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | If Langfuse |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | If Langfuse |
| `POSTHOG_PROJECT_API_KEY` | PostHog API key (OTel collector) | If PostHog |
| `GCP_PROJECT_ID` | Google Cloud project (OTel collector) | If GCP logging |
| `ATELIER_SERVICE_PORT` | HTTP service port (default: 8787) | No |
| `ATELIER_REQUIRE_AUTH` | Enable Bearer auth (`true`/`false`) | No |
| `ATELIER_ROOT` / `ATELIER_STACK_ROOT` | Custom data store root | No |
| `ATELIER_PROFILE` | Install profile: `stable` or `dev` | No |

---

*Integration audit: 2025-01-27*
