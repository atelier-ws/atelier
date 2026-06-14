# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

**All Python commands must use `uv run`** — the project uses `uv` for dependency management and there is no activated venv. Direct `python3` calls will fail or use the wrong environment.

```bash
uv run python -c "..."          # one-off Python
uv run pytest ...               # tests
uv run mypy src                 # type-check
uv run atelier ...              # CLI
```

The `.venv` is at `.venv/bin/python3` if you need the path explicitly.

## Common Commands

```bash
# Test
uv run pytest -q                          # all tests (slow tests excluded by default)
uv run pytest -q -x -m "not slow"        # fast, stop on first failure
uv run pytest tests/path/test_file.py -q # single file
uv run pytest -q -k "test_name"          # single test by name

# Lint / format / typecheck
make lint           # ruff
make format         # ruff --fix + black + prettier (frontend)
make typecheck      # mypy --strict src

# Full pre-commit gate
make pre-commit     # format + lint + typecheck + docs + test

# Docs governance
make sync-agent-context   # regenerate host instruction files from integrations/shared/
make check-agent-context  # verify generated files are up to date

# Install Claude plugin (after changing integrations/claude/plugin/)
bash scripts/install_claude.sh
```

## Architecture

The codebase has three layers with strict dependency direction:

```
gateway/  →  core/  →  infra/
```

- **`src/atelier/gateway/`** — all agent-facing entry points: `cli.py` (the `atelier` CLI), `mcp_server.py` (stdio MCP server for Claude/Codex/Gemini), `runtime.py` (façade for in-process SDK use). Keep entry-point logic thin here.
- **`src/atelier/core/`** — domain logic: `capabilities/` (context reuse, routing, tool supervision, proof gating, semantic memory, code-intel engine), `foundation/` (Pydantic models, SQLite store, paths), `runtime/engine.py` (orchestrator), `service/api.py` (FastAPI HTTP surface).
- **`src/atelier/infra/`** — persistence and integrations: `storage/` (SQLite/Postgres), `runtime/` (run ledger, realtime context), `code_intel/` (SCIP index, ast-grep, Zoekt), `embeddings/`, `memory_bridges/`.

**Key invariant:** New capabilities go in `core/capabilities/`, not in `mcp_server.py` or `cli.py`. Those files are dispatchers only.

## Claude Plugin / Hooks

The Claude Code integration lives in `integrations/claude/plugin/`. After any change:

```bash
bash scripts/install_claude.sh   # stages and reinstalls the plugin
```

Hook scripts run on Claude Code events:

- `hooks/stop.py` — session stats display and auto-record at stop
- `hooks/session_start.py` — session metadata capture
- `hooks/pre_tool_use.py`, `post_tool_use.py` — tool-level savings tracking
- `hooks/session_telemetry.py` — per-tool event emission to `~/.atelier/live_savings_events.jsonl`

Session state is persisted to `~/.atelier/workspaces/<hash>/session_state.json`. Savings for the stop hook come from `~/.atelier/session_stats/<claude-session-uuid>.json`.

## Data / State Layout

All runtime state lives under `~/.atelier/` (or `$ATELIER_ROOT`):

| Path                                   | Contents                                                                                    |
| -------------------------------------- | ------------------------------------------------------------------------------------------- |
| `runs/<session_id>.json`               | Run ledger — events, traces, token stats                                                    |
| `session_stats/<uuid>.json`            | Per-session savings keyed by Claude Code UUID                                               |
| `live_savings_events.jsonl`            | Append-only savings event log (uses internal Atelier session IDs,**not** Claude Code UUIDs) |
| `workspaces/<hash>/session_state.json` | Hook-to-hook state for a workspace                                                          |
| `smart_state.json`                     | Cumulative savings counters                                                                 |

## Source of Truth Hierarchy

Generated files must never be edited directly — edit the source and regenerate:

| Generated file                                                 | Source                        | Regenerate with                  |
| -------------------------------------------------------------- | ----------------------------- | -------------------------------- |
| `AGENTS.md`, `copilot-instructions.md`, host instruction files | `integrations/agents/`, `integrations/shared/` | `make sync-agent-context`        |
| Plugin staging dir `~/.atelier/claude-plugin-*/`               | `integrations/claude/plugin/` | `bash scripts/install_claude.sh` |

## Coding Guidelines

The full guidelines (think before coding, simplicity first, surgical changes, goal-driven execution) are embedded in every Atelier persona. Source of truth: `integrations/shared/coding-guidelines.md` — do not restate them here.

## Validation by Change Surface

| What changed                                       | Minimum check                                                                                    |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Python runtime / CLI                               | `make lint && make typecheck && make test`                                                       |
| Hook scripts (`integrations/claude/plugin/hooks/`) | `python3 -m py_compile <file>` then reinstall and smoke-test                                     |
| MCP tool handlers                                  | `uv run pytest tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_p0_mcp_surfaces.py -q` |
| Code-intel engine                                  | `uv run pytest tests/core/test_code_context.py -q && make lint && make typecheck`                |
| Frontend                                           | `cd frontend && npm run build && npm run test`                                                   |
| Docs / host instruction sources                    | `make docs-check && make check-agent-context`                                                    |

## Agent Spawning Rules

The atelier:code persona carries the role table. `/code-review` specifics: Phase-1 finders → `atelier:explore`, Phase-2 verifiers → `atelier:review`. Never use the default `claude` agent for a task that fits a typed role — it has write access it doesn't need and costs more.

## Code Intelligence

Prefer the focused SCIP-backed tools (`symbols`, `node`, `callers`/`callees`, `usages`, `codemod`, `explore`) over grep. Each is a dedicated tool that calls the code-intel engine directly — there is no `op=` multiplexer and no `mcp__atelier__code` tool. `symbols` is search-only; the repo/admin ops (`index`, `outline`, `hover`, `blame`, `rename`, `cache_status`, `cache_invalidate`) are registered as hidden internal tools, callable by name but not surfaced to agents.
