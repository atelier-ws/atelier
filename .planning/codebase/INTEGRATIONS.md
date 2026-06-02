# External Integrations

**Analysis Date:** 2026-06-02

## APIs & External Services

- OpenAI-compatible chat endpoints are supported for internal background processing via `src/atelier/infra/internal_llm/openai_client.py`; the client can target OpenAI directly or compatible providers through `ATELIER_OPENAI_BASE_URL`.
- Local Ollama models are supported through `src/atelier/infra/internal_llm/ollama_client.py`.
- Langfuse trace emission is optional and fail-open in `src/atelier/gateway/integrations/langfuse.py`.
- OpenMemory sidecar integration is implemented over MCP-over-HTTP in `src/atelier/gateway/integrations/openmemory.py` and via the memory bridge in `src/atelier/infra/memory_bridges/openmemory.py`.
- Letta sidecar-backed memory is handled in `src/atelier/infra/memory_bridges/letta_adapter.py`.
- Agent-host integrations ship as generated configs and plugins for Claude, Codex, Copilot, OpenCode, Cursor, Hermes, and Antigravity in `src/atelier/gateway/hosts/configs/*.yaml` and `integrations/*`.

## Data Storage

- SQLite is the default backend for runtime state (`src/atelier/infra/storage/sqlite_store.py`, `src/atelier/infra/storage/sqlite_memory_store.py`).
- PostgreSQL is optional through `src/atelier/infra/storage/postgres_store.py` and `.env.production.example`.
- Vector storage is optional through `src/atelier/infra/storage/vector.py` and the `vector` dependency group in `pyproject.toml`.
- Runtime state defaults to `~/.atelier`; project-local lessons default to `<workspace>/.lessons` (`src/atelier/core/foundation/paths.py`).
- Swarm runs, logs, stack state, and ledgers are file-backed under the Atelier root (`src/atelier/core/capabilities/swarm/capability.py`, `src/atelier/infra/runtime/stack_lifecycle.py`, `src/atelier/infra/runtime/run_ledger.py`).

## Authentication & Identity

- Service API auth is optional locally and enforced with Bearer tokens when `ATELIER_REQUIRE_AUTH=true` (`src/atelier/core/service/auth.py`, `.env.production.example`).
- Remote client calls attach `Authorization: Bearer <ATELIER_API_KEY>` when configured (`src/atelier/gateway/adapters/remote_client.py`).
- Host installation/registration uses fingerprinted host records under `.atelier/hosts/` (`src/atelier/gateway/hosts/registry.py`).
- Product telemetry/session IDs are anonymized and emitted from CLI and MCP surfaces (`src/atelier/gateway/cli/app.py`, `src/atelier/gateway/adapters/mcp_server.py`).

## Monitoring & Observability

- OpenTelemetry exporters are included in backend dependencies and collector configs live in `deploy/otel-collector.yaml` and `deploy/otel-collector-dev.yaml`.
- Frontend analytics use `posthog-js` (`frontend/package.json`).
- Runtime/event tracking is anchored in `src/atelier/core/service/telemetry/` and `src/atelier/infra/runtime/run_ledger.py`.
- Claude/Codex/Copilot hook scripts emit session and tool telemetry from `integrations/claude/plugin/hooks/`, `integrations/codex/hooks/`, and `integrations/copilot-cli/hooks/`.

## CI/CD & Deployment

- CI runs CodeQL, lint/format, typecheck, tests, dependency audit, and install-script checks in `.github/workflows/tests.yml`.
- Release packaging and GitHub releases are automated in `.github/workflows/release.yml`.
- Native install/bootstrap is handled by `scripts/install.sh`; host-specific verification/install flows live in `integrations/*/install.sh` and `integrations/*/verify.sh`.
- Local container orchestration is defined in `docker-compose.yml`.

## Environment Configuration

- Production env expectations are documented in `.env.production.example`.
- Service config is materialized lazily from environment variables in `src/atelier/core/service/config.py`.
- Host-specific MCP settings are templated in `src/atelier/gateway/hosts/configs/*.yaml` and generated/copied into `integrations/`.
- Frontend-to-service linkage uses `VITE_API_URL` (`docker-compose.yml`, `frontend/src/api.ts`).

## Webhooks & Callbacks

- No public third-party webhook receiver layer stood out in the repo scan; the dominant callback model is local host hooks rather than SaaS webhooks.
- Claude plugin hooks for session start/stop and tool events live in `integrations/claude/plugin/hooks/hooks.json` and related Python scripts.
- Codex and Copilot CLI integrations also install hook entrypoints (`integrations/codex/hooks/`, `integrations/copilot-cli/hooks/`).
- OpenMemory's HTTP MCP transport behaves like a callback-style sidecar protocol managed in `src/atelier/gateway/integrations/openmemory.py`.

---

*Integration analysis: 2026-06-02*
*Update after adding/removing providers or deployment targets*
