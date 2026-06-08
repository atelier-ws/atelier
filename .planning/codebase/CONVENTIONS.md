# Coding Conventions

**Analysis Date:** 2026-06-08

This codebase is a Python 3.12+ runtime (`src/atelier/`) plus a React/TypeScript frontend (`frontend/`). The Python backend is the primary surface; follow its conventions for nearly all work. Source-of-truth coding guidance also lives in `integrations/shared/coding-guidelines.md` (generated into `AGENTS.md`/`CLAUDE.md`).

## Naming Patterns

**Files:**
- Python modules are `snake_case.py` — `host_router_bridge.py`, `session_report.py`, `usage_sync.py`.
- One cohesive responsibility per module; module docstring states it (e.g. `"""Domain bundle loader — reads bundle.yaml and asset files from disk."""`).
- Frontend files are `.ts`/`.tsx` under `frontend/src/`.

**Functions:**
- Public functions: `snake_case` — `usage_cost_usd`, `resolve_workspace_root`, `build_swarm_apply_payload`.
- Private/internal helpers: leading underscore `_snake_case` — `_utcnow`, `_get_trace`, `_ensure_eval_blocks_exist`. Underscore-prefixed helpers are heavily used (~1575 vs ~1007 public defs) — prefer a module-private helper over exporting incidental logic.

**Variables:**
- `snake_case` for locals and module constants that are mutable.
- Module-level constants: `UPPER_SNAKE` — `_REQUIRED_FIELDS`, `BUILTIN_ROOT`.

**Types:**
- Classes: `PascalCase` — `DomainLoader`, `ContextStore`, `HermesAdapter`, `AdapterDecision`.
- Adapter/config pairs follow a `XxxConfig` / `XxxAdapter` naming convention (`HermesConfig`/`HermesAdapter`, `CursorConfig`/`CursorAdapter`).
- Custom exceptions end in `Error` (or domain-specific `Unavailable`) — `SymbolEditError`, `RouteConfigError`, `OllamaUnavailable`, `SleeptimeUnavailable`.
- `Literal[...]` type aliases for closed enumerations — `BlockStatus = Literal["active", "deprecated", "quarantined"]` in `src/atelier/core/foundation/models.py`.

## Code Style

**Formatting:**
- `black` is the formatter — `make format` runs `ruff check --fix` then `black src tests`.
- `[tool.black]` in `pyproject.toml`: `line-length = 120`, `target-version = ["py312"]`.
- Note the line-length mismatch: `ruff` uses `line-length = 100` but ignores `E501`, while `black` wraps at 120. Treat 120 as the effective limit; do not hand-wrap to 100.
- `make format-check` runs `black --check src tests` (CI gate).

**Linting:**
- `ruff` — `make lint` runs `ruff check src benchmarks tests scripts integrations`.
- Enabled rule sets (`[tool.ruff.lint]`): `E`, `F`, `I` (import sort), `B` (bugbear), `BLE` (blind-except), `UP` (pyupgrade), `RUF`. `E501` is ignored.
- `target-version = "py312"` — use modern syntax (`X | Y` unions, `list[...]`, `dict[...]`, `match` where it reads well).

**Type checking:**
- `mypy` in **strict** mode (`make typecheck` → `mypy --explicit-package-bases src benchmarks tests scripts integrations`).
- `[tool.mypy]`: `strict = true`, `warn_unused_ignores = false`, `ignore_missing_imports = true`, `warn_return_any = false`.
- Annotate all function signatures and return types. `406/453` source files use `from __future__ import annotations`.

## Import Organization

**Order (ruff `I` enforces):**
1. `from __future__ import annotations` (first line after docstring — near-universal).
2. Standard library — `import json`, `from pathlib import Path`, `from datetime import UTC, datetime`.
3. Third-party — `from pydantic import BaseModel, ConfigDict, Field`, `from fastapi import Header, HTTPException`.
4. First-party — `from atelier.core.foundation.models import Trace`.

**Path conventions:**
- Absolute imports from the `atelier.` root package; no relative `..` imports across packages.
- Heavy use of explicit multi-name imports (one symbol per line in parens) for readability — see `src/atelier/core/service/api.py` swarm import block.
- Use `TYPE_CHECKING` guards for import-only-for-typing to avoid runtime cost / cycles:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from atelier.core.foundation.store import ContextStore
  ```

## Error Handling

**Patterns:**
- `raise ValueError(...)` is the dominant validation error (~289 uses) with an f-string message including the offending value: `raise ValueError(f"bundle.yaml missing required fields {missing}: {manifest}")`.
- `raise RuntimeError(...)` for invariant/operational failures (~65 uses); `NotImplementedError` for abstract surfaces.
- Define **domain-specific exception subclasses** for distinct subsystems rather than reusing built-ins — `SymbolEditError`, `RouteConfigError`, `NoFeasibleRouteError`, `SyncError`, `TeamPermissionError`, `InternalLLMError`. Place them near the subsystem they serve.
- Messages include concrete context (path, field name, expected vs actual) — never bare `raise ValueError("invalid")`.

**Broad-except recovery:**
- Where resilience matters (loaders iterating untrusted files), catch broadly but log and continue, never swallow silently:
  ```python
  except Exception as exc:
      logging.exception("Recovered from broad exception handler")
      log.warning("skipping malformed bundle %s: %s", candidate.name, exc)
  ```
- `ruff` `BLE` is enabled — blind `except:` without rationale will be flagged. Always bind `as exc` and log.

## Logging

**Framework:** stdlib `logging`. Module-level logger declared once per module (~59 modules):
```python
log = logging.getLogger(__name__)
```

**Patterns:**
- Use `%`-style lazy formatting, not f-strings, in log calls: `log.warning("skipping malformed bundle %s: %s", candidate.name, exc)`.
- `logging.exception(...)` inside except blocks to capture traceback.
- **Never log secrets.** API keys are explicitly never logged (`src/atelier/core/service/auth.py` docstring). Do not add logging that emits `Authorization` headers, API keys, or env secret values.

## Comments & Docstrings

**Module docstrings:** Required — every module opens with a one-line (often multi-line) `"""..."""` describing its responsibility, sometimes with usage examples (see `src/atelier/core/service/api.py`).

**Class/function docstrings:** Public classes and functions carry a concise docstring stating purpose and contract; helpers explaining non-obvious behavior get a sentence (see `_no_ollama` fixture in `tests/conftest.py`).

**Section banners:** Long modules use comment-banner separators to group regions:
```python
# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
```
Tests use `# ===...===` banners to group importer/subject sections.

**When to comment:** Explain *why*, invariants, and forward-compat contracts (e.g. "Field names are kept stable... so traces remain forward-compatible"). Do not comment obvious code. Per `AGENTS.md`: don't "improve" adjacent comments/formatting unrelated to your change.

## Function & Data Model Design

**Data models:**
- `pydantic.BaseModel` for contracts crossing layers / API boundaries (~42 modules) — store, retriever, API schemas. Field names are stable and explicit; use `Field(...)`, `ConfigDict`, `field_validator`, `model_validator`.
- `@dataclass` for internal value objects and config bundles (~121 modules) — lighter weight, no validation overhead.
- Choose `BaseModel` when data is serialized/validated at a boundary; choose `@dataclass` for in-process structs.
- Closed string sets are `Literal[...]` aliases, not loose `str`.

**Functions:**
- Small, single-purpose; return typed values (`list[DomainBundle]`, `Trace`).
- Accept `Path | str` and normalize with `Path(...)` at the boundary (see `DomainLoader.load`).
- Use timezone-aware UTC: `datetime.now(UTC)` via a `_utcnow()` helper, never naive `datetime.now()`.

## Module Design

**Exports:** No explicit `__all__` convention; underscore prefix marks privates. Packages expose curated names via `__init__.py` (e.g. `from atelier.infra.internal_llm import OllamaUnavailable`).

**Layout:** Layered packages under `src/atelier/`: `core/` (foundation, service, runtime, domains, rubrics, capabilities), `gateway/` (cli, adapters, hosts, sdk), `infra/` (storage, embeddings, code_intel, tree_sitter, internal_llm), `sdk/`, `bench/`. Keep new code in the layer matching its responsibility.

## Frontend (TypeScript/React)

- React 18 + TypeScript 5 + Vite, under `frontend/src/`. Strict `tsc` typecheck (`npm run typecheck`).
- TailwindCSS for styling; `react-router-dom` for routing; `lucide-react` icons.
- Build: `tsc -b && vite build`. This is a secondary surface — backend conventions dominate.

## Pre-Commit Expectations

Before opening a PR run `make pre-commit` (and `make verify` for fuller validation: lint, format-check, typecheck, docs-check, test). The repo ships a pre-push hook enabled via `git config core.hooksPath .githooks`.

---

*Convention analysis: 2026-06-08*
