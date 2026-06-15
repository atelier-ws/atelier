# Testing Patterns

**Analysis Date:** 2026-06-08

The backend uses **pytest** (310 `test_*.py` files under `tests/`). The frontend uses **Vitest**. Backend testing is the primary surface.

## Test Framework

**Runner:**
- `pytest` >= 8.0 (dev dependency in `pyproject.toml`).
- Config: `[tool.pytest.ini_options]` in `pyproject.toml`.
- `pytest-cov` >= 5.0 for coverage; `pytest-xdist` used opportunistically for parallelism (`-n auto --dist=worksteal` when `xdist` importable).

**Assertion Library:**
- Plain Python `assert` (pytest rewriting). Assertions carry explanatory messages:
  `assert len(traces) == 1, f"Expected 1 trace for host={host}, got {len(traces)}"`.

**Config highlights (`pyproject.toml`):**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers -m 'not slow'"
pythonpath = ["src", "."]
markers = [
    "slow: marks tests as slow",
    "ab: real A/B benchmark for MCP tool savings",
]
```
- `--strict-markers`: unregistered markers fail — register new markers in `pyproject.toml`.
- Default run **excludes** `slow` tests (`-m 'not slow'`). `slow` is the most-used marker (~52 files).
- `pythonpath = ["src", "."]` lets tests import `atelier.*` and `tests.*` without installation.

**Run Commands (`Makefile`):**
```bash
make test           # Full suite, parallel via xdist if available, --durations=0
make test-fast      # -x stop-on-first-failure, skips postgres/worker + slow tests
make test-cov       # --cov=atelier --cov-report=term-missing --cov-report=html
make test-full      # FULL suite incl. slow, --timeout=300, --cov-fail-under=$(COV_FAIL_UNDER)
make verify         # lint + format-check + typecheck + docs-check + test
```
Direct: `uv run pytest -q -ra`, target a file with `uv run pytest tests/core/test_x.py -v`.

## Test File Organization

**Location:** Separate `tests/` tree mirroring the source layout — `tests/core/`, `tests/gateway/`, `tests/infra/`, `tests/integrations/`, `tests/benchmarks/`, `tests/docs/`, `tests/golden/`. Tests are NOT co-located with source.

**Naming:**
- Files: `test_<subject>.py` — `test_session_importer_tokens.py`, `test_security.py`.
- A few real A/B benchmark files use `_ab_real.py` suffix — `test_code_routes_ab_real.py`.
- Functions: `def test_<behavior>(...)` with descriptive snake_case names — `test_claude_prefers_embedded_session_id_over_filename`, `test_readme_no_unmeasured_claims`.

**Structure:**
```
tests/
├── conftest.py                  # single root conftest — all shared fixtures live here
├── fixtures/                    # static test data (jsonl, yaml, json, golden/, languages/)
│   ├── 200_failed_traces.jsonl
│   ├── archival_eval_questions.yaml
│   └── golden/
├── core/  gateway/  infra/  integrations/  benchmarks/  docs/  golden/
```

## Test Structure

**Two styles coexist** — choose by cohesion:

1. **Module-level functions** (default for simple/standalone checks):
```python
def test_v2_savings_yaml_does_not_claim_a_percentage_target() -> None:
    path = Path("benchmarks/swe/prompts_11.yaml")
    text = path.read_text(encoding="utf-8").lower()
    forbidden = ["reduction_pct", "50 %", "50%", "actual:", "target:"]
    assert not any(term in text for term in forbidden)
```

2. **Class grouping** (`class TestXxx:`) when many tests share a subject — used to group the 5+ session importers:
```python
class TestClaudeImporterTokens:
    """Claude: Anthropic's disjoint-cache convention."""
    def test_claude_token_fields(self) -> None:
        ...
```
- Test functions are annotated `-> None`. Shared private helpers in the module use leading underscore (`_get_trace`, `_assert_tool_tokens`) and live under a `# === Helpers ===` banner.

**Parametrization:** `@pytest.mark.parametrize` is used (~17 files) to table-drive variants; one fixture even parametrizes backends (`params=["sqlite", "letta", "open..."]`).

## Fixtures

**All shared fixtures live in the single root `tests/conftest.py`** (`"""Shared pytest fixtures."""`). There is only one conftest in the tree — add shared fixtures there.

**Autouse isolation fixtures (critical — they run for every test):**
- `_isolate_workspace_env` — deletes host workspace env vars (`ATELIER_WORKSPACE_ROOT`, `CLAUDE_WORKSPACE_ROOT`, etc.) and points `ATELIER_ROOT`/`ATELIER_STORE_ROOT` at `tmp_path/.atelier`. Tests never touch the real workspace.
- `_no_network_sync` — patches `atelier.core.service.usage_sync.sync_usage` so no test hits `atelier.beseam.com`.
- `_no_ollama` — patches `atelier.infra.internal_llm.ollama_client._ollama_module` to raise `OllamaUnavailable`, blocking real local-LLM calls. Override via `monkeypatch` when a test needs LLM behavior.

**Common explicit fixtures:**
- `store(tmp_path)` — builds a `ContextStore` rooted in `tmp_path` (`@pytest.fixture()`).
- `retrieval_eval_runtime` — `scope="session"` runtime seeded once via `tmp_path_factory`.
- Standard pytest fixtures used throughout: `tmp_path`, `tmp_path_factory`, `monkeypatch`.

**Scopes seen:** function (default `@pytest.fixture()`, ~25), `autouse=True` (~9), `scope="class"`, `scope="session"`, parametrized `params=[...]`.

## Mocking

**Framework:** stdlib `unittest.mock` (`patch`, `MagicMock`) plus pytest `monkeypatch`. ~110 test files use mocking.

**Patterns:**
```python
from unittest.mock import patch
with patch("atelier.core.service.usage_sync.sync_usage", return_value=True):
    yield
# or side_effect to simulate failure:
with patch("...ollama_client._ollama_module", side_effect=OllamaUnavailable("blocked")):
    yield
```
- Patch at the **single chokepoint** the real code routes through (e.g. `_ollama_module()` gateway) so mocks hold even for `from ... import summarize` callers. Prefer patching the source definition, not each importer.
- Use `monkeypatch.setenv/delenv` for environment; `monkeypatch.setattr` for targeted overrides.

**What to mock:** outbound network (usage sync, remote APIs), local LLMs (Ollama), external services. The autouse fixtures already block these globally.

**What NOT to mock:** the `ContextStore` and filesystem — use real stores rooted in `tmp_path`. Tests prefer real objects against temp dirs over mocks for the system under test.

## Fixtures & Test Data

**Static data:** `tests/fixtures/` holds golden/seed data — `200_failed_traces.jsonl`, `archival_eval_questions.yaml`, `savings_baseline.json`, `fixtures/golden/`, `fixtures/languages/`.
**Synthetic data:** importer tests build inline synthetic fixtures (one tool turn + one no-tool turn) rather than relying on large static files.
**Golden tests:** `tests/golden/` (incl. `golden/optimization/`) compare output against committed expected artifacts.

## Coverage

**Floor:** Enforced only on the full slow-inclusive suite via `make test-full` → `--cov-fail-under=$(COV_FAIL_UNDER)` (`COV_FAIL_UNDER` defined in `Makefile`, used by `nightly-coverage.yml`). The default fast suite does not gate coverage.

**View coverage:**
```bash
make test-cov   # term-missing + HTML report (htmlcov/)
```

## Test Types

**Unit tests:** Dominant — token extraction, model validation, loaders, adapters. Real objects against `tmp_path`.

**Integration tests:** `tests/integrations/`, plus DB-backed suites (`tests/test_postgres_store.py`, `tests/test_worker_jobs.py`) that `test-fast` deliberately ignores (need Postgres).

**Security tests:** `tests/gateway/test_security.py` — included in `make test` / `make test-full`.

**Docs/contract tests:** `tests/docs/` asserts docs/README don't publish forbidden or unmeasured claims (e.g. `test_readme_no_unmeasured_claims`) — guardrails on documentation honesty.

**Benchmark / A/B tests:** `tests/benchmarks/` and `*_ab_real.py` files, gated behind the `ab` and `slow` markers and env flags (e.g. `LOCAL=1` for the proof-cost-quality gate).

## Common Patterns

**Marking slow / special tests:**
```python
import pytest

@pytest.mark.slow
def test_expensive_replay() -> None:
    ...
```
Register any new marker in `pyproject.toml` `markers` (because `--strict-markers`).

**Assertion with diagnostics:** always include an f-string message on non-trivial asserts so CI failures are self-explanatory.

**Frontend tests:** Vitest + `@testing-library/react` + jsdom, run via `npm run test` (`node ./scripts/run-vitest.mjs`) in `frontend/`.

---

*Testing analysis: 2026-06-08*
