# Contributing

## Prerequisites

- Python 3.12+
- `uv` package manager: `pip install uv`
- Git

## Setup

```bash
cd atelier
uv sync --all-extras
uv run atelier init
```

## Development Commands

```bash
make verify        # Full gate: ruff + black --check + mypy strict + pytest
make pre-commit    # Format, lint, typecheck, tests (run before committing)
make lint          # ruff check (no fix)
make fmt           # ruff + black format (applies fixes)
make typecheck     # mypy strict
make test          # pytest (all tests)
make test-fast     # pytest -x --no-cov (stop on first failure)
make test-cov      # pytest with coverage report
make security-test # Security-focused test cases only
```

## Test Suite

```bash
cd atelier && uv run pytest
```

Expected: **209 passed, 9 skipped**

The 9 skips are Postgres-gated tests. They require `ATELIER_DATABASE_URL=postgresql+asyncpg://...` and are skipped when only SQLite is configured. This is **not a failure**.

To run Postgres-gated tests:

```bash
ATELIER_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/atelier \
uv run pytest
```

## Running Backend + Frontend Tests (e-commerce project)

```bash
cd backend && uv run pytest        # Backend unit tests
cd frontend && npm test            # Frontend unit tests
```

Do not run these inside the atelier directory — they are separate test suites.

## Code Style

- **Type hints** on all function signatures (enforced by mypy strict)
- **Async functions** for all I/O
- **Pydantic models** for all data validation
- **ruff** for linting
- **black** for formatting
- No `# type: ignore` without a comment explaining why

## Adding a New Module

1. Create `src/atelier/your_module/` with `__init__.py`
2. Add Pydantic schemas in `schemas.py`
3. Add core logic in separate files — never mix I/O and business logic
4. Register any new CLI commands in `src/atelier/adapters/cli.py`
5. Register any new MCP tools in `src/atelier/adapters/mcp_server.py`
6. Write tests in `tests/test_your_module.py`
7. Update `atelier/AGENT_README.md` and any relevant parent READMEs

## Never Modify Generated Files

- `src/atelier/adapters/mcp_server.py` tool schemas are generated from Pydantic models — update models, not the generated output
- `frontend/src/services/stub/` in the e-commerce project is generated from OpenAPI spec — run `make generate-stub` after API changes

## Pull Request Guidelines

1. Run `make pre-commit` and fix all errors before opening PR
2. Include test coverage for all new behavior
3. Update `AGENT_README.md` for any directories you touch
4. Create an ADR (`docs/internal/engineering/decisions/NNN-description.md`) for significant design decisions
5. Never commit directly — human review required per project rules

## Project Architecture Notes

- **PYTHONPATH**: The project uses `PYTHONPATH=/app/src:$PYTHONPATH` — imports use `from atelier.xxx import yyy`
- **Entry points**: `atelier` CLI and `atelier-mcp` MCP server are defined in `pyproject.toml`
- **LOCAL=1**: For running Python scripts outside Docker: `cd atelier && LOCAL=1 uv run python scripts/my_script.py`
