# Testing Patterns

**Analysis Date:** 2026-06-02

## Test Framework

**Runner:**
- pytest for backend/runtime tests (`pyproject.toml`, `Makefile`, `tests/`).
- Vitest + jsdom for frontend tests (`frontend/package.json`, `frontend/scripts/run-vitest.mjs`).

**Assertion Library:**
- pytest's native assertions plus fixtures/markers for Python.
- Testing Library + Vitest assertions for React (`frontend/src/pages/Swarm.test.tsx` and sibling test files).

**Run Commands:**
```bash
make test
make test-fast
make test-full
make lint
make typecheck
cd frontend && npm run test && npm run build
```

## Test File Organization

**Location:**
- Backend tests are split by surface: `tests/gateway/`, `tests/core/`, `tests/infra/`.
- Shared pytest fixtures live in `tests/conftest.py`.
- Frontend tests sit beside UI code in `frontend/src/pages/*.test.tsx`.
- Benchmark verification lives under both `benchmarks/` assets and backend test modules like `tests/gateway/test_swe_benchmark_harness.py`.

**Naming:**
- Python: `test_<topic>.py`
- Frontend: `<Page>.test.tsx`
- Smoke/contract tests call out the target surface in the filename (`test_mcp_tool_handlers.py`, `test_service_api.py`, `Swarm.test.tsx`).

## Test Structure

**Suite Organization:**
- Pytest modules lean on helper builders and fixture repos (`tests/core/test_code_context.py`, `tests/gateway/test_mcp_tool_handlers.py`).
- CLI surfaces are exercised via `click.testing.CliRunner` (`tests/gateway/test_mcp_tool_handlers.py`).
- Frontend tests render pages/components with `@testing-library/react` and route context (`frontend/src/pages/Swarm.test.tsx`).

**Patterns:**
- Heavy use of temp directories and isolated workspace roots to avoid touching the developer's real `~/.atelier` or `.lessons/` state (`tests/conftest.py`).
- Backend tests frequently construct miniature fixture repos in code for deterministic code-intel scenarios (`tests/core/test_code_context.py`).
- Frontend tests mock `fetch` and assert on JSON payload shape rather than talking to a live service (`frontend/src/pages/Swarm.test.tsx`).

## Mocking

**Framework:**
- `unittest.mock.patch`, `MagicMock`, and `pytest.monkeypatch` on the Python side (`tests/conftest.py`, `tests/gateway/test_mcp_tool_handlers.py`).
- `vi.spyOn` / `vi.mock` in the frontend (`frontend/src/pages/Swarm.test.tsx`).

**What Gets Mocked:**
- Network sync and Ollama calls are globally blocked in tests (`tests/conftest.py`).
- External clients and host surfaces are replaced with mocks/fakes in gateway tests.
- Browser/network APIs (`fetch`) are mocked in frontend page tests.

## Fixtures and Factories

- `tests/conftest.py` provides autouse isolation fixtures plus seeded runtime/store helpers.
- `tests/fixtures/` contains reusable fixture assets for broader suites.
- Many core tests build ad hoc fixture repositories inline with helper functions, keeping test inputs close to the assertions (`tests/core/test_code_context.py`).
- Benchmark fixtures and generated cases live under `benchmarks/` and specialized test helpers.

## Coverage

- Default pytest run excludes `slow` tests (`pyproject.toml`).
- `make test-full` enforces a coverage floor (`COV_FAIL_UNDER ?= 66`) in `Makefile`.
- CI runs lint, typecheck, pytest on Python 3.11 and 3.13, dependency audit, and CodeQL in `.github/workflows/tests.yml`.
- Frontend coverage is behavioral/component-level through Vitest; no separate browser E2E framework is currently declared in `frontend/package.json`.

## Test Types

- Unit tests: isolated core/infra helpers and capability logic (`tests/core/`, `tests/infra/`).
- Contract/API tests: MCP, CLI, service API, and install surfaces (`tests/gateway/`).
- Integration tests: storage, session parsing, swarm, telemetry, and code-intel subsystems.
- Frontend interaction tests: page-level UI with mocked backend responses (`frontend/src/pages/*.test.tsx`).
- Benchmark/regression tests: benchmark harness generation and proof/savings flows (`benchmarks/`, `tests/gateway/test_swe_benchmark_harness.py`).

## Common Patterns

- Use `tmp_path` and env isolation to keep tests hermetic (`tests/conftest.py`).
- Prefer explicit helper builders over opaque fixtures for complex repositories (`tests/core/test_code_context.py`).
- Model HTTP/API responses as JSON helper functions in frontend tests (`frontend/src/pages/Swarm.test.tsx`).
- Treat host/runtime install flows as first-class tested surfaces, not manual-only behavior (`tests/gateway/test_agent_cli_install_artifacts.py`, `.github/workflows/tests.yml`).

---

*Testing analysis: 2026-06-02*
*Update when the test stack, commands, or layout changes*
