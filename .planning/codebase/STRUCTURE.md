# Codebase Structure

**Analysis Date:** 2026-06-02

## Directory Layout

```text
src/
  atelier/
    gateway/      host-facing CLI/MCP/SDK/adapters
    core/         capabilities, models, service, orchestrator
    infra/        storage, code-intel, runtime services, sidecars
    sdk/          public middleware helpers
  benchmarks/     packaged benchmark helpers
frontend/         optional React dashboard
integrations/     host-specific install/plugin assets
tests/            backend and integration tests
benchmarks/       benchmark suites and harness data
docs/             product and agent-os source docs
scripts/          install, verification, generation, maintenance
deploy/           collector and sidecar deployment configs
templates/        runtime prompt/reasonblock templates
```

## Directory Purposes

- `src/atelier/gateway/` - CLI commands, MCP handlers, host parsers/configs, SDK/local adapters.
- `src/atelier/core/` - the product's main behavior, especially `capabilities/`, `foundation/`, `runtime/`, and `service/`.
- `src/atelier/infra/` - concrete implementations for persistence, embeddings, code-intel, and runtime bookkeeping.
- `frontend/` - React dashboard pages/components plus API client.
- `integrations/` - installable/generated artifacts for Claude, Codex, Copilot, Cursor, Hermes, Antigravity, and OpenCode.
- `docs/agent-os/` - source-of-truth instruction blocks that generate `AGENTS.md`, `copilot-instructions.md`, and host wrappers.
- `benchmarks/` and `src/benchmarks/` - benchmark harnesses, benchmark projects, VIX/terminalbench/SWE assets.
- `tests/` - large pytest suite split by surface (`gateway/`, `core/`, `infra/`).

## Key File Locations

- Product metadata / deps: `pyproject.toml`, `uv.lock`
- Primary CLI entry: `src/atelier/gateway/cli/app.py`
- MCP server: `src/atelier/gateway/adapters/mcp_server.py`
- Runtime orchestrator: `src/atelier/core/runtime/engine.py`
- HTTP API: `src/atelier/core/service/api.py`
- Path/runtime root helpers: `src/atelier/core/foundation/paths.py`
- Host configs: `src/atelier/gateway/hosts/configs/*.yaml`
- Frontend shell/API client: `frontend/src/App.tsx`, `frontend/src/api.ts`
- Install/bootstrap flow: `scripts/install.sh`
- CI/release: `.github/workflows/tests.yml`, `.github/workflows/release.yml`

## Naming Conventions

- Python modules/packages use `snake_case` (`run_ledger.py`, `sqlite_memory_store.py`).
- React pages/components use `PascalCase` filenames (`Swarm.tsx`, `Overview.tsx`, `WorkbenchUI.tsx`).
- Pytest files use `test_*.py`; frontend tests sit beside pages/components as `*.test.tsx`.
- Host configs are `{host}.yaml`; generated instruction/install assets use host-specific top-level folders in `integrations/`.
- Environment variables are consistently prefixed with `ATELIER_`.

## Where to Add New Code

- New host-facing commands/adapters belong under `src/atelier/gateway/`.
- New product capabilities belong under `src/atelier/core/capabilities/`, not inside the CLI or MCP entrypoints.
- New storage, runtime backend, or sidecar implementations belong under `src/atelier/infra/`.
- UI pages go in `frontend/src/pages/`; shared frontend primitives belong in `frontend/src/components/` or `frontend/src/lib/`.
- New host installation surfaces should extend `docs/agent-os/` + `src/atelier/gateway/hosts/configs/` and then regenerate `integrations/`.

## Special Directories

- `.lessons/` - project-local learned blocks/rubrics when present.
- `.codegraph/`, `semantic_file_index.json` - code-intel related artifacts/caches.
- `artifacts/`, `reports/` - generated outputs from runtime/benchmark/reporting flows.
- `docs-site/` and `docs-archive/` - separate documentation publishing/history surfaces.
- `internal/`, `notes/`, `program.md`, `AGENTS.md`, `CLAUDE.md` - repository governance and project guidance outside runtime code.

---

*Structure analysis: 2026-06-02*
*Update when major directories move or new surfaces are added*
