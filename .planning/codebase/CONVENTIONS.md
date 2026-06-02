# Coding Conventions

**Analysis Date:** 2026-06-02

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

---

*Convention analysis: 2026-06-02*
*Update when repo-wide style or layering rules change*
