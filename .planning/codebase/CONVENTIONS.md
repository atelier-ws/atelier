# Coding Conventions

**Analysis Date:** 2025-01-31

## Code Style

**Formatter:** Black (`line-length = 120`, `target-version = ["py311"]`)

**Linter:** Ruff (`line-length = 100`, `target-version = "py311"`)
- Active rule sets: `E`, `F`, `I`, `B`, `UP`, `SIM`, `RUF`
- `E501` (line-too-long) is ignored — black handles wrapping

**Run formatting:**
```bash
uv run ruff check --fix src/         # auto-fix lint issues
uv run black src/                    # format
uv run black --check src tests       # CI format check
uv run ruff check src/               # lint check only
```

**Section Dividers:** Source files use dashed comment banners to visually separate sections:
```python
# --------------------------------------------------------------------------- #
# Section Name                                                                #
# --------------------------------------------------------------------------- #
```
This pattern is prominent in `src/atelier/core/foundation/models.py`, `store.py`, and capability files.

## Type Annotations

**Python version:** 3.11+ syntax throughout.

**Future annotations import:** Every source file opens with `from __future__ import annotations` (342 of 387 source files). This is mandatory — add it to every new file.

**Union syntax:** Use `X | Y` and `X | None`, never `Optional[X]` or `Union[X, Y]`. The codebase has 0 uses of `Optional[]` or `Union[]`.

**Return types:** All public and private functions must have explicit return type annotations.

**TYPE_CHECKING guard:** Used for 26 forward-reference imports to avoid circular imports at runtime:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from atelier.gateway.adapters.runtime import ContextRuntime
```

**mypy:** Strict mode enforced. Run with `make typecheck` / `uv run mypy --strict src/`.

**Overrides in `pyproject.toml`:**
- `atelier.core.service.api` and `atelier.gateway.adapters.http_api`: `disable_error_code = ["untyped-decorator"]` (FastAPI route decorators)
- `atelier.gateway.adapters.cli`: `ignore_errors = true` (Click CLI boilerplate)

**Sample annotation style:**
```python
def load_policy(root: Path | str) -> GovernancePolicy:
    ...

def recommend(
    self,
    *,
    tool_name: str,
    task_text: str,
    session_state: Mapping[str, Any] | None = None,
    actual_vendor: str | None = None,
) -> dict[str, Any]:
    ...
```

## Pydantic Models

All data models extend `pydantic.BaseModel`. Key conventions:

**`extra="forbid"` on every model:**
```python
class ReasonBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
```
This makes schema drift a hard error, not silent data loss.

**Mutable defaults use `Field(default_factory=...)`:**
```python
triggers: list[str] = Field(default_factory=list)
task_types: list[str] = Field(default_factory=list)
```

**Validators use `@field_validator` / `@model_validator` (Pydantic v2):**
```python
@field_validator("procedure")
@classmethod
def _procedure_non_empty(cls, v: list[str]) -> list[str]:
    if not v:
        raise ValueError("procedure must contain at least one step")
    return v
```

**Serialization:** Use `model.model_dump(mode="python")` for YAML/dict round-trips; `model_validate(data)` for deserialization.

**Frozen dataclasses for value objects:** Internal recommendation/result objects use `@dataclass(frozen=True)` instead of Pydantic for immutable value objects:
```python
@dataclass(frozen=True)
class RankedCandidate:
    vendor: str
    model: str
    tier: str
    estimated_cost_usd: float
    reasons: tuple[str, ...] = ()
```
Location: `src/atelier/core/capabilities/cross_vendor_routing/router.py`

## Error Handling

**Domain-specific exception classes:** Raise custom exceptions subclassed from the most appropriate built-in:
```python
class NoFeasibleRouteError(ValueError):
    """Raised when no configured vendor can satisfy the requested turn safely."""

class RouteConfigError(ValueError):
    ...
```

**Chained exceptions:** Use `raise NewError(...) from exc` when wrapping:
```python
except RoutePolicyError as exc:
    raise NoFeasibleRouteError(str(exc)) from exc
```

**No bare `except:`** — Always catch specific exception types.

**Validation errors:** Let Pydantic `ValidationError` surface unmodified — tests assert on it directly.

**HTTP errors:** FastAPI `HTTPException` is raised in API adapters (`src/atelier/core/service/api.py`); core/capabilities never import HTTPException.

## Naming Patterns

**Files:**
- `snake_case.py` everywhere
- Capability modules follow a fixed layout: `models.py`, `capability.py`, `store.py` per domain

**Functions and variables:** `snake_case`

**Classes:** `PascalCase`

**Private methods/functions:** `_leading_underscore`

**Module-level loggers:**
- Gateway adapters: `logger = logging.getLogger(__name__)`
- Core capabilities and infra: `_log = logging.getLogger(__name__)` (prefixed underscore signals non-public)

**Type aliases (Literal unions):**
```python
BlockStatus = Literal["active", "deprecated", "quarantined"]
TraceStatus = Literal["success", "failed", "partial"]
BlockTier = Literal["e1", "e2", "e3"]
```
Defined in `src/atelier/core/foundation/models.py` and used as field types.

**Keyword-only arguments:** Public methods that accept more than 2 parameters use `*` to enforce keyword-only calling:
```python
def recommend(self, *, tool_name: str, task_text: str, session_state: ...) -> ...:
```

## Import Organization

Managed by ruff's `I` rule (isort-compatible). Order:

1. `from __future__ import annotations` (always first)
2. Standard library (`collections`, `dataclasses`, `datetime`, `pathlib`, `typing`, ...)
3. Third-party (`pydantic`, `yaml`, `click`, `fastapi`, ...)
4. Internal absolute imports (`from atelier.core...`, `from atelier.infra...`)
5. Relative imports (`from .configuration import ...`, `from . import ...`)

**Example:**
```python
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from atelier.core.capabilities.lesson_promotion.store import TypedLessonStore
from atelier.core.capabilities.model_routing.router import ModelRouter

from .configuration import RouteConfig, detect_configured_vendors
from .policy import RoutePolicyError, allowed_vendors
```

## Module Structure

**File header pattern:**
```python
"""One-line module description.

Extended explanation if needed. This is the contract between layers,
design decisions, etc.
"""

from __future__ import annotations

# ... imports ...

# --------------------------------------------------------------------------- #
# Helpers / constants                                                          #
# --------------------------------------------------------------------------- #

# ... private helpers ...

# --------------------------------------------------------------------------- #
# Public classes / functions                                                   #
# --------------------------------------------------------------------------- #

# ... public API ...
```

**`__all__`:** Used selectively in `gateway/` layer (`__init__.py`, `registry.py`, `session_parsers/__init__.py`, `sdk/__init__.py`). Core capabilities do not define `__all__`.

## Logging

**Setup per module:**
```python
import logging
logger = logging.getLogger(__name__)   # gateway adapters
_log = logging.getLogger(__name__)     # core capabilities / infra
```

**No structured logging library** — standard `logging` module only. No `structlog`, no `loguru`.

**When to log:** Log at the adapter/gateway layer for external calls and errors. Core logic uses `_log.warning(...)` / `_log.debug(...)` sparingly. Never log secrets or API keys.

## Docstrings

**Module docstrings:** Present on all files in `core/` and `infra/`. Explain purpose and key design decisions. Multi-paragraph is fine when documenting schema or backend choices.

**Class docstrings:** Short one-liners. Describe what the class *is*, not how it works.

**Function docstrings:** Sparse — private helpers generally undocumented. Public API methods get a docstring only if the signature doesn't self-document.

**No NumPy/Google/Sphinx style** — plain imperative English prose.

---

*Convention analysis: 2025-01-31*
