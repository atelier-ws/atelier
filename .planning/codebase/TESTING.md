# Testing Patterns

**Analysis Date:** 2025-01-31

## Test Framework

**Runner:** pytest 9.x
- Config: `pyproject.toml` `[tool.pytest.ini_options]`
- `testpaths = ["tests"]`
- `addopts = "-ra --strict-markers -m 'not slow'"` — slow tests excluded by default
- `pythonpath = ["src", "."]`

**Assertion library:** plain `assert` statements (pytest rewriting)

**Parallelism:** `pytest-xdist` — `make test` uses `-n auto --dist=loadfile` when xdist is available

**Coverage:** `pytest-cov` — no minimum threshold enforced

**HTTP testing:** FastAPI `TestClient` (`httpx`-backed) — no real server started

**Mocking:** `unittest.mock` (`patch`, `MagicMock`) + pytest `monkeypatch` fixture

## Test Commands

```bash
make test                             # full suite (xdist parallel if available)
make test-fast                        # -x stop-on-fail, skip Postgres/worker, -m "not slow"
make test-cov                         # with terminal + HTML coverage reports
make security-test                    # tests/gateway/test_security.py only
make docs-check                       # tests/gateway/test_docs.py + test_generated_agent_contexts.py

uv run pytest -q                      # quiet run (uses default -m "not slow")
uv run pytest -q -x                   # stop on first failure
uv run pytest -q -m slow              # run slow tests only
uv run pytest -q -m ab                # run A/B benchmark tests
uv run pytest -q tests/core/          # run a specific subtree
uv run pytest -q tests/infra/test_store.py   # single file
uv run pytest --cov=atelier --cov-report=term-missing --cov-report=html
```

## Test File Organization

**Structure:** Mirrors `src/atelier/` under `tests/`:
```
tests/
├── conftest.py                      # global autouse fixtures
├── core/                            # mirrors src/atelier/core/
│   ├── capabilities/
│   │   ├── cross_vendor_routing/    # one file per behaviour
│   │   │   ├── test_advisor_returns_cheapest_capable.py
│   │   │   ├── test_advisor_skips_unconfigured_vendor.py
│   │   │   └── test_route_yaml_is_round_trippable.py
│   │   ├── lesson_promotion/        # one file per behaviour
│   │   └── prompt_compilation/
│   └── service/
├── gateway/                         # mirrors src/atelier/gateway/
│   ├── test_service_api.py          # large: full HTTP API coverage
│   └── test_security.py
├── infra/                           # mirrors src/atelier/infra/
│   ├── test_store.py
│   └── test_outcome_capture.py      # large: grouped by class
├── benchmarks/                      # performance / A/B tests
│   └── code_intel/
├── fixtures/                        # static fixture files (JSONL, YAML, JSON)
│   ├── optimization/
│   ├── memory/
│   ├── golden/
│   └── savings_baseline.json
└── golden/                          # golden output files for snapshot tests
```

**Naming conventions:**
- Files: `test_{behaviour_being_verified}.py`
- Functions: `def test_{sentence_describing_expected_outcome}(...)` — full sentence names
- Classes: `class TestXxx:` when grouping related behaviours (large test files)

## Test Structure

**Single-function style (capability tests):**
Each capability subdirectory uses one file per behaviour — typically one test function per file:
```python
# tests/core/capabilities/cross_vendor_routing/test_advisor_returns_cheapest_capable.py
from __future__ import annotations

from atelier.core.capabilities.cross_vendor_routing.configuration import RouteConfig
from atelier.core.capabilities.cross_vendor_routing.router import CrossVendorRouter


def test_advisor_returns_cheapest_capable(tmp_path) -> None:
    router = CrossVendorRouter(
        RouteConfig(enabled_vendors=["anthropic", "openai", "google"]),
        env={"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k", "GOOGLE_API_KEY": "k"},
    )
    recommendation = router.recommend(
        tool_name="read",
        task_text="find the failing test",
        session_state={"expected_input_tokens": 1200, ...},
    )
    assert recommendation.vendor == "google"
    assert recommendation.model == "gemini-2.0-flash"
```

**Class-grouped style (larger test files):**
```python
# tests/infra/test_outcome_capture.py
class TestRouteScore:
    def test_perfect_score(self) -> None:
        assert _route_score(0, 0, 0) == 1.0

    def test_retry_penalty(self) -> None:
        score = _route_score(retries_same_tool=1, model_errors_in_window=0, extra_reads=0)
        assert abs(score - 0.6) < 1e-6

class TestAdvanceRoute:
    def test_fills_window_after_five_turns(self) -> None:
        ...
```

**Section dividers in large test files:**
```python
# --------------------------------------------------------------------------- #
# Score formula tests                                                          #
# --------------------------------------------------------------------------- #
```

**Helper factories in test files:**
```python
def _block(bid: str = "b1", domain: str = "coding", **kw: object) -> ReasonBlock:
    """Build a minimal valid ReasonBlock for testing."""
    base: dict[str, Any] = dict(id=bid, title="Title", ...)
    base.update(kw)
    return ReasonBlock(**base)
```
Private helper functions (prefix `_`) at module level provide minimal valid test objects.

**Arrange / Act / Assert:** No explicit labels — layout is implicitly AAA.

## Fixtures

**Global fixtures (`tests/conftest.py`):**

```python
@pytest.fixture(autouse=True)
def _no_network_sync() -> Iterator[None]:
    """Block all outbound sync_usage calls so no test ever hits atelier.beseam.com."""
    with patch("atelier.core.service.usage_sync.sync_usage", return_value=True):
        yield

@pytest.fixture(autouse=True)
def _no_ollama() -> Iterator[None]:
    """Block real Ollama calls so no test waits on a local LLM."""
    with patch(
        "atelier.infra.internal_llm.ollama_client._ollama_module",
        side_effect=OllamaUnavailable("ollama blocked in tests"),
    ):
        yield

@pytest.fixture()
def store(tmp_path: Path) -> ContextStore:
    s = ContextStore(tmp_path / "atelier")
    s.init()
    return s

@pytest.fixture()
def seeded_runtime(tmp_path: Path) -> Iterator[ContextRuntime]:
    """Runtime backed by the bundled seed blocks + rubrics."""
    ...
```

**Key rules about global fixtures:**
- `_no_network_sync` and `_no_ollama` are `autouse=True` — all tests get them without opt-in
- Tests that need LLM behaviour override these via `monkeypatch`
- `store` fixture creates a fresh `ContextStore` in `tmp_path` — use this for all store-dependent tests

**Local fixtures (per test file):**
Defined at module level in test files when scope is narrow:
```python
# tests/gateway/test_service_api.py
@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    st = SQLiteStore(tmp_path / ".atelier")
    st.init()
    return st

@pytest.fixture()
def app_no_auth(store: SQLiteStore, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """App with auth disabled."""
    monkeypatch.setenv("ATELIER_REQUIRE_AUTH", "false")
    return cast("TestClient", FastAPITestClient(create_app(store_root=store.root)))
```

**Static fixture files:**
- `tests/fixtures/optimization/` — optimization scenario JSON
- `tests/fixtures/memory/` — memory test data
- `tests/fixtures/200_failed_traces.jsonl` — failure trace corpus
- `tests/fixtures/archival_eval_questions.yaml` — eval questions
- `tests/fixtures/savings_baseline.json` — benchmark baseline

## Mocking Approach

**Two tools, different use cases:**

### `unittest.mock.patch` — module-level patching
Used for blocking outbound calls and replacing module globals:
```python
from unittest.mock import patch

with patch("atelier.core.service.usage_sync.sync_usage", return_value=True):
    yield

with patch(
    "atelier.infra.internal_llm.ollama_client._ollama_module",
    side_effect=OllamaUnavailable("blocked"),
):
    yield
```

### `monkeypatch` — environment and attribute patching
Used for environment variables and module attribute replacement:
```python
def test_foo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_REQUIRE_AUTH", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(mcp_server, "_REMOTE_TOOLS", frozenset())
    monkeypatch.delenv("ATELIER_DEV_MODE", raising=False)
```

### `MagicMock` — object stubs
Used when an interface needs partial implementation:
```python
from unittest.mock import MagicMock

mock_store = MagicMock()
mock_store.get_block.return_value = None
```

**What to mock:**
- All outbound network calls (autouse fixtures handle sync/ollama globally)
- LLM API calls in unit tests (real calls only in `@pytest.mark.ab` tests)
- Filesystem paths — always use `tmp_path` instead of mocking

**What NOT to mock:**
- SQLite store — use real in-memory store via `store` fixture
- Pydantic models — test real validation
- Pure business logic functions — test directly

## Optional Dependency Guards

For tests requiring optional extras (`fastapi`, `uvicorn`, `mcp`):
```python
# Module-level skip if package absent
pytest.importorskip("fastapi", reason="FastAPI API tests require the api extra")

# Inside a test
FastAPITestClient = pytest.importorskip(
    "fastapi.testclient",
    reason="FastAPI API tests require the api extra",
).TestClient
```

## Pytest Markers

**Registered markers (`pyproject.toml`):**
```toml
markers = [
    "slow: marks tests as slow",
    "ab: real A/B benchmark; writes to ~/.atelier/savings_calibration.jsonl",
]
```

**Usage:**
```python
pytestmark = pytest.mark.slow   # file-level — all tests in file are slow

@pytest.mark.slow               # function-level
def test_expensive(): ...

pytestmark = pytest.mark.ab     # A/B benchmarks — run with `make bench-ab`
```

**Default behaviour:** `addopts = "-m 'not slow'"` — slow tests never run in `make test` or `uv run pytest`. Run them explicitly with `uv run pytest -m slow`.

## Exception Testing

```python
with pytest.raises(ValidationError):
    ReasonBlock(procedure=[])  # empty procedure violates validator

with pytest.raises(ValueError, match="seed_files is required when mode='map'"):
    some_function(mode="map")
```
Use `match=` parameter to assert on error message content.

## Parametrize

Used selectively, mainly in gateway and benchmark tests:
```python
@pytest.mark.parametrize("host", ["codex", "opencode", "copilot", "antigravity"])
def test_host_install_artifacts(host: str) -> None:
    ...

@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_read_ab(fixture: Path) -> None:
    ...
```

## Coverage

**No minimum threshold enforced.**

```bash
make test-cov                   # terminal + HTML reports
uv run pytest --cov=atelier --cov-report=term-missing --cov-report=html
```

HTML report written to `htmlcov/`. Clean with `make clean`.

## Test Count Summary

- 235 test files total
- ~1,666 test functions
- Excluded by default: `@pytest.mark.slow`, `@pytest.mark.ab`
- Auto-excluded files in `make test-fast`: `tests/test_postgres_store.py`, `tests/test_worker_jobs.py`

---

*Testing analysis: 2025-01-31*
