# Stack Research

**Domain:** Terminal-first agent runtime brownfield retrofit
**Researched:** 2026-06-02
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11+ | Core runtime, CLI, MCP, service, integrations | Existing Atelier is already Python-first, and the runtime/memory/code-intel stack is concentrated here. Brownfield retrofit should preserve this instead of rewriting in a new language. |
| FastAPI + Pydantic | FastAPI >=0.136.1, Pydantic >=2.6 | HTTP/service surfaces and typed runtime contracts | Already present in Atelier and appropriate for typed internal APIs, reports, and service endpoints. |
| Click | >=8.1 | Terminal CLI surface | Existing CLI is already Click-based and remains the right fit for a terminal-first product. |
| LiteLLM | >=1.83.14 | Model/provider abstraction and routing support | Already gives Atelier a strong vendor abstraction layer to build real subcall routing on top of. |
| Tree-sitter | >=0.23 | Code-intel, structure-aware reads, future minified read/edit path | Existing code-intel strength depends on syntax-aware indexing; this is also the best base for Eval-style compression features. |
| SQLite / PostgreSQL | SQLite default, PostgreSQL optional | Runtime state, memory, benchmark/report persistence | SQLite keeps the local terminal-first path cheap; PostgreSQL remains the scale-up path when needed. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tiktoken` | >=0.9 | Token accounting and benchmark cost tracking | Required for trustworthy savings/cost measurement. |
| `GitPython` + `pygit2` | >=3.1.50 / 1.19.2 | Repo-aware operations, worktree flows, patch application | Keep for runtime/git-aware execution and future workflow kernel coordination. |
| `sqlalchemy` | >=2.0.49 | Storage abstraction | Use for durable runtime/report/config state rather than ad hoc persistence. |
| OpenTelemetry packages | >=1.27 | Runtime telemetry/export | Use for service/report observability and benchmark artifact plumbing. |
| React + Vite | React 18.3.1, Vite 5.4.21 | Optional UI/service visualization | Keep as a secondary surface only; do not let it drive milestone 1. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `uv` | Python dependency/runtime management | This repo already standardizes on `uv run ...`; keep it as the only Python execution path. |
| Ruff + Black + mypy | Lint, format, type-check | Existing repo standards; keep strictness rather than lowering quality to move faster. |
| pytest + Vitest | Backend/frontend validation | Use pytest for runtime/integration and Vitest for optional UI. |
| Docker Compose | Local service/frontend stack | Useful for non-terminal surfaces, but not core to milestone 1. |

## Installation

```bash
# Backend/runtime
uv sync

# Frontend (optional surface)
cd frontend && npm install

# Run backend checks
make lint
make typecheck
uv run pytest -q
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Brownfield Python retrofit | Go rewrite around a fresh daemon kernel | Only if the current Python runtime proves structurally incapable of the target loop, which is not supported by current research. |
| Search-first composed tool path | Brand new monolithic tool runtime | Only if composition fails badly in practice; milestone 1 should reuse existing code-intel/memory surfaces first. |
| SQLite default + Postgres optional | Postgres-first everywhere | Use Postgres when multi-user/service scale genuinely demands it. |
| Host-native top-level chat + Atelier-owned routed subcalls | Full top-level host override | Defer until measured parity shows the routing layer is reliable enough. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Clean-slate rewrite | Discards Atelier's strongest existing advantages and restarts architectural risk from zero | Brownfield extraction and focused retrofit |
| Generic grep-only default path | Would regress Atelier's sharper code-intel differentiation | Search-first path that composes read/search with code-intel escalation |
| Full provider enforcement on day one | Too risky while routing is still mostly advisory in current Atelier | Enforced routing only for Atelier-owned subcalls |
| Web-first expansion as milestone 1 | Pulls attention away from terminal quality/cost goals | Terminal-first core with optional UI kept secondary |

## Stack Patterns by Variant

**If the work is on the terminal-first core:**
- Keep Python runtime + Click + MCP/server surfaces primary
- Prioritize tree-sitter/code-intel, routing, workflow state, and benchmark instrumentation

**If the work is on service/dashboard support:**
- Keep FastAPI + React as secondary reporting/operations surfaces
- Avoid letting frontend concerns drive core workflow decisions

**If the work is on routing experiments:**
- Reuse LiteLLM and existing routing logic
- Add new provider execution only where Atelier owns the subcall

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Python 3.11+ | Pydantic 2.x, FastAPI 0.136+, Ruff target py311 | Already the repo baseline |
| React 18.3.1 | React Router 6.26.0, Vite 5.4.21, TypeScript 5.5.3 | Current frontend stack is internally aligned |
| Tree-sitter >=0.23 | tree-sitter-language-pack >=1.8.1 | Important for structure-aware code-intel paths |

## Sources

- `pyproject.toml`
- `frontend/package.json`
- `.planning/codebase/STACK.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/research/RESET-RESEARCH.md`

---
*Stack research for: terminal-first agent runtime brownfield retrofit*
*Researched: 2026-06-02*
