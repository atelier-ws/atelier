# Tool substitution — MANDATORY

Atelier tools are **not optional wrappers**. They are the reason this repo exists. Using native tools here is eating your own savings.

| Instead of | Use | Why | Measured |
|---|---|---|---|
| `Read(file)` | `mcp__atelier__read` | outline-first; large files return structure without bytes | **Measured token savings (cl100k_base) from `tests/benchmarks/test_read_ab_real.py`:** Ruby 97.2%, C++ 94.4%, Python 85.6%, Markdown 84.5%, TypeScript 74.0%, Shell 69.9%, Scala 50.6%. Current C/C#/Go/Java/Kotlin/PHP/Rust/Swift fixtures still hit full-read fallback (0%) at their base sizes. |
| recursive `find` / `glob` inventory loops | `mcp__atelier__code op=files` | indexed file tree/list/grouped view without filesystem scanning | **Fixture A/B (`tests/benchmarks/test_code_files_ab_real.py`):** 1,908 → 517 tokens (72.9% fewer; 1,391 tokens saved) for a nested Python repo inventory flow. |
| `Bash(grep ...)` / `Bash(rg ...)` | `mcp__atelier__grep` | regex/glob/type-filter search with token-budgeted output shaping | **Fixture A/B (`tests/benchmarks/test_search_ab_real.py`):** summary mode 1,908 → 165 tokens (91.4% fewer; 1,743 tokens saved). Tiny regex/glob/context fixtures are near parity (0% saved). |
| manual grep + read + rank workflow | `mcp__atelier__search` | ranked query search plus repo-map construction | **Fixture A/B (`tests/benchmarks/test_search_ab_real.py`):** summary mode 1,908 → 197 tokens (89.7% fewer; 1,711 tokens saved). Tiny regex/glob/context fixtures currently favor native output volume. |
| `mcp__atelier__code op=files` | `find` / `glob` inventory loops | indexed file tree/list/grouped view without filesystem scanning | **Fixture A/B (`tests/benchmarks/test_code_files_ab_real.py`):** 1,908 → 517 tokens (72.9% fewer; 1,391 tokens saved) for nested repo inventory. |
| `mcp__atelier__code op=search` | `Bash(grep -rn symbol ...)` | SCIP-indexed; no subprocess | **Fixture A/B (`tests/benchmarks/test_code_search_ab_real.py`):** 2,142 → 432 tokens (79.8% fewer; 1,710 tokens saved) for symbol discovery across a Python module set. || `Bash(anything)` | `mcp__atelier__shell` | ANSI-stripped + line-truncated output | **Fixture A/B (`tests/benchmarks/test_shell_ab_real.py`):** 5,001 → 377 tokens (92.5% fewer; 4,624 tokens saved) on large command output (`seq 1 2000`) with line truncation. |
| `Edit(...)` / `Write(...)` | `mcp__atelier__edit` | atomic multi-file with snapshot/rollback | **Fixture A/B (`tests/benchmarks/test_edit_ab_real.py`):** 74 → 47 tokens (36.5% fewer; 27 tokens saved) for single-file replace response vs manual patch/diff transcript. |
| chaining search + symbol + callers/callees + read | `mcp__atelier__code op=explore` | grouped source + relationships in one budgeted call | **Fixture A/B (`tests/benchmarks/test_code_explore_ab_real.py`):** 3,510 → 1,927 tokens (45.1% fewer; 1,583 tokens saved) for an auth/login exploration flow. |
| manual grep+read route inventory | `mcp__atelier__code op=routes` | framework route nodes (method/path/handler) in one call | **Fixture A/B (`tests/benchmarks/test_code_routes_ab_real.py`):** 690 → 332 tokens (51.9% fewer; 358 tokens saved) for mixed FastAPI/Django/Express route discovery. |

> Every "X% saved" claim in this row must cite a real A/B test under `tests/benchmarks/`. If the test isn't there, the cell reads `_pending A/B_`. No exceptions.
>
> Run `make bench-ab` to refresh the calibration store at `~/.atelier/savings_calibration.jsonl`.

## Exceptions (native tools are fine)

- `Read` when Atelier MCP is not available / returns `noop`.
- `Edit`/`Write` for tiny single-line fixes where the edit is trivially correct.
- `Bash` for git commands (already auto-allowed, no token overhead).

## MCP server priority — Atelier first, always

Atelier tools take priority over ALL other MCP servers (CodeGraph, etc.) for overlapping capability domains. This is not a suggestion — it's the design of the system.

| Atelier tool | Replaces from other MCP servers | Why Atelier wins |
|---|---|---|
| `mcp__atelier__code` (all ops: `search`, `node`, `callers`, `callees`, `impact`, `context`, `explore`, `files`, `routes`) | CodeGraph `search`, `node`, `callers`, `callees`, `impact`, `context`, `explore`, `files` | SCIP-indexed, token-budgeted, project-aware — one tool replaces an entire MCP server |
| `mcp__atelier__grep` | Any grep/search tool from other servers | Regex/glob/type-filter with token-budgeted output shaping |
| `mcp__atelier__read` | Any file-read tool from other servers | Outline mode saves 50-95% tokens on large files |
| `mcp__atelier__edit` | Any edit/write tool from other servers | Atomic multi-file with snapshot/rollback, diff recorded |
| `mcp__atelier__search` | Any semantic/ranked search | Budget-capped ranked results, repo-map mode |

**Decision rules:**

1. **Symbol lookup, definition, callers, callees, impact analysis, file tree, routes, code context** → `mcp__atelier__code` FIRST. Do NOT reach for CodeGraph.
2. **Regex/grep, text search** → `mcp__atelier__grep` FIRST.
3. **File reading** → `mcp__atelier__read` FIRST.
4. **Editing** → `mcp__atelier__edit` FIRST.
5. **Shell commands** → `mcp__atelier__shell` FIRST.

**Use other MCP servers ONLY when:**
- The Atelier equivalent returns `noop` or is unavailable.
- The other server provides a unique capability Atelier does not cover (e.g., web search, external API access, database access).

Do NOT use CodeGraph for code-intel tasks. Atelier's `code` tool handles all of them with better token efficiency and native project awareness. Using CodeGraph when Atelier is available wastes context and duplicates work.

## Model routing — use cheap sub-agents for read work

Before spawning an `Agent(...)` for a read-only task, call `mcp__atelier__route` to get the recommended model tier. Read/search/explore tasks should spawn as `Agent(model="haiku")`. Edit/implement tasks stay on the current model.

```
# exploration, file reading, grep work
Agent(model="haiku", description="...", prompt="...")

# implementation, editing, multi-file changes
Agent(...)  # current model
```

**Cross-vendor routing** (`route.yaml` at `~/.atelier/route.yaml`) is configured for Anthropic only until `OPENAI_API_KEY` / `GOOGLE_API_KEY` are set. Token-efficiency savings (`mcp__atelier__read`, `mcp__atelier__search`) work regardless of vendor.

## Tooling conventions

### Python

- **Always use `uv run` instead of bare `python` or `python3`** — the project uses `uv` for environment management.
  - `uv run pytest tests/ -x -q`
  - `uv run python -c "import atelier; ..."`
  - NOT `python -m pytest` (wrong venv)
  - NOT `python3 src/...` (not in project env)
- Source lives under `src/`; Python path is `["src", "."]` (set in `pyproject.toml`).
- Run tests: `uv run pytest tests/ -x -q --tb=short`
- Type-check: `uv run mypy src/atelier/`
- Lint/format: `uv run ruff check src/` and `uv run ruff format src/`

### Package management

- Add deps: `uv add <package>` (updates `pyproject.toml` + `uv.lock`)
- Add optional dep to an extra: edit `pyproject.toml` `[project.optional-dependencies]` manually, then `uv sync`
- Install extras: `uv sync --extra rename` (example)
- Never use `pip install` directly inside this repo.

### MCP server

- Entry point: `uv run atelier-mcp` (registered script in `pyproject.toml`)
- Dev server with reload: `uv run uvicorn atelier.gateway.adapters.http_api:app --reload`
- All MCP tools are registered in `src/atelier/gateway/adapters/mcp_server.py` via `@mcp_tool(name=...)`.
- **Do NOT add new top-level `@mcp_tool` entries** unless a milestone file explicitly says so; add new `op=` values to existing tools instead.

### Frontend

- Lives in `frontend/`; uses Vite + React.
- `cd frontend && npm run dev` for local dev.
- Docker: `docker-compose up` starts both API and frontend.

### Scripts

- `make install` — full local install via `scripts/install.sh --local`
- `make status` — show install status
- `scripts/sync_agent_context.py` — regenerates AGENTS.md / GEMINI.md / copilot-instructions.md from `docs/agent-os/README.md`; run after editing that file.

## Known behavioural gaps

These are tool behaviours that can confuse an LLM. They are not bugs — they are design boundaries that now have built-in handling in the MCP server code.

### `atelier_read` on a directory — handled (no longer an error)

**Status: ✅ Fixed in server** (`src/atelier/gateway/adapters/mcp_server.py`)

`atelier_read` now detects when the given path is a directory and returns a structured
response with `mode: "directory"`, the list of entries, and a directive for next steps,
instead of raising a cryptic `file not found` error.

### `atelier_code op=files` — blind to non-code files

**Status: ✅ Fixed in server** (`src/atelier/gateway/adapters/mcp_server.py`)

`atelier_code op=files` queries a symbol index that only tracks files with
parseable code symbols (Python, TypeScript, JavaScript, Rust, Go, C++, Java, etc.).
Non-code files — YAML, Markdown, JSON, TOML, shell scripts, Dockerfiles, configs —
are invisible to `op=files` even though they exist on disk.

The server now detects when `op=files` returns 0 results for a path that exists on
disk, and **automatically falls back** to a native filesystem listing. The response
includes `non_code_fallback: true` to signal that files were listed from the
filesystem rather than the code index.

**Manual workaround (if fallback doesn't apply):**

```
# List YAML files in a directory:
atelier_grep(
    file_path="some/dir",
    output_mode="file_paths_only",
    file_glob_patterns=["*.yaml"],
)

# List ALL files (including non-code):
atelier_shell(command="ls path/to/dir")
```
