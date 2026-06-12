# Codebase Structure

**Analysis Date:** 2026-06-08

## Directory Layout

```
atelier/
├── src/
│   ├── atelier/             # Main Python package (453 .py files)
│   │   ├── gateway/         # Agent-facing entry points (CLI, MCP, adapters, SDK, hosts)
│   │   ├── core/            # Domain logic (runtime, capabilities, foundation, service)
│   │   ├── infra/           # Persistence + integrations (storage, code_intel, embeddings)
│   │   ├── sdk/             # Framework middleware (langchain/openai/anthropic/gemini)
│   │   └── bench/           # Benchmark mode helpers
│   └── benchmarks/          # Benchmark harness package (swe, code_intel)
├── frontend/                # React + Vite + Tailwind analytics dashboard
│   └── src/                 # pages/, components/, lib/, test/
├── integrations/            # Host integration sources (claude, codex, cursor, copilot, …)
│   ├── agents/ shared/      # Source for generated agent-context files
│   └── claude/plugin/       # Claude Code plugin + hooks
├── tests/                   # Pytest suite (core, gateway, infra, integrations, golden, …)
├── benchmarks/              # Workspace member: atelierbench, mcp_tools, swe, terminalbench
├── scripts/                 # Dev/install/governance scripts
├── deploy/  docker-compose.yml  Dockerfile.api  Dockerfile.frontend
├── docs/  docs-site/  docs-archive/  examples/  templates/  installer/
├── pyproject.toml  uv.lock  Makefile
└── AGENTS.md  CLAUDE.md  README.md  QUICK_REFERENCE.md  (CLAUDE/AGENTS are generated)
```

## Directory Purposes

**`src/atelier/gateway/`:**

- Purpose: All agent-facing entry points; thin dispatchers only.
- Contains: `cli/` (Click app + `commands/`), `adapters/` (mcp_server, host adapters, `runtime.py`), `sdk/` (client/local/remote/mcp), `hosts/` (registry, session_parsers, configs), `integrations/` (langfuse, openmemory, analytics).
- Key files: `cli/app.py`, `adapters/mcp_server.py`, `adapters/runtime.py`.

**`src/atelier/core/`:**

- Purpose: Domain logic and orchestration.
- Contains: `runtime/engine.py`, `capabilities/` (~60 feature packages), `foundation/` (models/store/retriever/renderer), `service/` (FastAPI), `domains/`, `rubrics/`, `improvement/`.
- Key files: `runtime/engine.py`, `service/api.py`, `foundation/models.py`, `foundation/store.py`.

**`src/atelier/infra/`:**

- Purpose: Persistence and external integrations.
- Contains: `storage/`, `runtime/` (run ledger, cost tracker), `code_intel/` (scip/astgrep/zoekt), `embeddings/`, `memory_bridges/`, `internal_llm/`, `seed_blocks/`, `tree_sitter/`.
- Key files: `storage/factory.py`, `runtime/run_ledger.py`, `internal_llm/litellm_client.py`.

**`frontend/`:**

- Purpose: React analytics dashboard over the HTTP API.
- Contains: `src/pages/` (Sessions, Savings, Insights, Memory, Swarm, Workflow, …), `src/components/`, `src/lib/`, `src/test/`.
- Key files: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/src/pages/Overview.tsx`.

**`integrations/`:**

- Purpose: Source-of-truth for host integrations and generated agent-context files.
- Contains: `agents/`, `shared/`, `claude/plugin/hooks/`, plus per-host dirs (codex, cursor, copilot, opencode, hermes, antigravity).

**`tests/`:**

- Purpose: Pytest suite mirroring package layers.
- Subdirs: `core/`, `gateway/`, `infra/`, `integrations/`, `benchmarks/`, `docs/`, `golden/`, `fixtures/`.

## Key File Locations

**Entry Points:**

- `src/atelier/gateway/cli/app.py`: CLI (`atelier`, `atl`).
- `src/atelier/gateway/adapters/mcp_server.py`: MCP stdio server (`atelier mcp`).
- `src/atelier/gateway/adapters/runtime.py`: in-process `ContextRuntime` façade.
- `src/atelier/core/service/api.py`: FastAPI `create_app`.
- `src/atelier/sdk/middleware.py`: framework middleware entry.

**Configuration:**

- `pyproject.toml`: deps, scripts, ruff/black/mypy/pytest config.
- `Makefile`: lint/format/typecheck/test/governance targets.
- `.env.production.example`: env template (do not commit secrets).
- `docker-compose.yml`, `Dockerfile.api`, `Dockerfile.frontend`: deployment.

**Core Logic:**

- `src/atelier/core/runtime/engine.py`: runtime orchestrator.
- `src/atelier/core/capabilities/`: feature packages.
- `src/atelier/core/foundation/models.py`: Pydantic models.

**Testing:**

- `tests/` (root), `frontend/src/**/*.test.tsx` (Vitest co-located).

## Naming Conventions

**Files:**

- Python modules: `snake_case.py` (e.g. `run_ledger.py`, `quality_router.py`).
- Capability packages: `snake_case/` directories under `core/capabilities/`.
- React components/pages: `PascalCase.tsx` (e.g. `SessionDetail.tsx`); tests `PascalCase.test.tsx`.
- Seed blocks: numbered kebab YAML (e.g. `01-concrete-anchor-before-edit.yaml`).

**Directories:**

- Layer roots: `gateway/`, `core/`, `infra/`, `sdk/`.
- Feature units: `snake_case/` package per capability.

## Where to Add New Code

**New capability/feature (the common case):**

- Implementation: `src/atelier/core/capabilities/<feature>/` (new package), wire into `src/atelier/core/runtime/engine.py`.
- Tests: `tests/core/...`
- Do NOT add logic to `mcp_server.py` or `cli/commands/*` — those are dispatchers only.

**New CLI command:**

- Implementation: `src/atelier/gateway/cli/commands/<name>.py`, register in `cli/app.py`.

**New host adapter / integration:**

- Implementation: `src/atelier/gateway/adapters/<host>_adapter.py` or `gateway/integrations/`.

**New storage/embedding backend:**

- Implementation: `src/atelier/infra/storage/` or `infra/embeddings/`, register in the corresponding `factory.py`.

**New frontend page:**

- Implementation: `frontend/src/pages/<Name>.tsx`, co-locate `<Name>.test.tsx`.

**New persistent model:**

- Implementation: `src/atelier/core/foundation/models.py` (or a focused `*_models.py`).

**Shared utilities:**

- Python: `src/atelier/core/foundation/`.
- Frontend: `frontend/src/lib/`.

## Special Directories

**`~/.atelier/` (runtime, not in repo):**

- Purpose: All runtime state (runs, session_stats, workspaces, live_savings_events, smart_state).
- Generated: Yes. Committed: No.

**Generated agent-context files (`AGENTS.md`, host instruction files, `CLAUDE.md`):**

- Purpose: Per-host instructions generated from `integrations/agents/` + `integrations/shared/`.
- Generated: Yes (via `make sync-agent-context`). Committed: Yes, but never hand-edit.

**`src/atelier/infra/seed_blocks/`:**

- Purpose: YAML seed reason blocks bundled into the wheel.
- Generated: No. Committed: Yes.

**`.venv/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `node_modules/`, `dist/`:**

- Purpose: Tooling caches and build output.
- Generated: Yes. Committed: No.

**`benchmarks/` and `integrations/` (uv workspace members):**

- Purpose: Separate workspace packages with their own `pyproject.toml`.
- Committed: Yes.

---

_Structure analysis: 2026-06-08_
