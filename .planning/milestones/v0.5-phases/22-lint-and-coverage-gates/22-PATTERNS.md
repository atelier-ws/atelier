# Phase 22: Lint and Coverage Gates - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 3 (2 modified, 1 created)
**Analogs found:** 3 / 3 (all in-repo, exact matches)

> This is a **config/CI phase** — no runtime source code is created. The three change
> surfaces are `pyproject.toml`, `Makefile`, and a new `.github/workflows/*.yml`. Every
> analog is an existing file in the same locations, so the planner/executor should copy
> structure and idioms verbatim rather than inventing new conventions.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `pyproject.toml` (modify `[tool.ruff.lint]`, add `[tool.ruff.lint.per-file-ignores]`) | config | declarative-config | same file, existing `[tool.ruff.lint]` + `[tool.mypy.overrides]` tables | exact (in-file precedent) |
| `Makefile` (add `test-full` target) | config / build-tooling | batch (command wrapper) | same file, existing `test-cov` + `test` targets | exact (in-file precedent) |
| `.github/workflows/nightly-coverage.yml` (create) | config / CI | event-driven (scheduled) | `.github/workflows/docs-governance.yml` (schedule+dispatch) and `tests.yml` `test` job (uv/test idioms) | exact |

## Pattern Assignments

### `pyproject.toml` — `[tool.ruff.lint]` select extension (config, declarative)

**Analog:** the existing `[tool.ruff.lint]` block in the same file.

**Current state** (`pyproject.toml` lines 102-108):
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]
```

**Target** (add `"BLE"`, `"T20"` to `select`; leave `ignore` untouched per QBL-GATE-02 / Pitfall 3):
```toml
[tool.ruff.lint]
select = ["E", "F", "I", "B", "BLE", "T20", "UP", "SIM", "RUF"]
ignore = ["E501"]
```

**Pattern to copy — the `[tool.mypy.overrides]` precedent** (lines 129-140) shows the
existing convention for *scoped, per-module rule relaxation* in this file. The new
`per-file-ignores` table follows the same "park specific modules, keep the global rule on"
philosophy:
```toml
[[tool.mypy.overrides]]
module = [
    "atelier.core.service.api",
    "atelier.gateway.adapters.http_api",
]
disable_error_code = ["untyped-decorator"]
```

### `pyproject.toml` — `[tool.ruff.lint.per-file-ignores]` table (config, declarative)

**Analog:** no existing ruff per-file-ignores table (this is additive — no conflict).
Closest precedent is the mypy override pattern above (scoped relaxation).

**Pattern (ruff 0.15.x syntax — glob keys relative to project root, value = list of codes):**
```toml
[tool.ruff.lint.per-file-ignores]
"src/atelier/gateway/adapters/mcp_server.py" = ["BLE001", "T201"]
"src/atelier/__init__.py" = ["BLE001"]
# ... 96 BLE001 files + 19 T201 files, with intersection files getting both codes
```

**Worklist source-of-truth (verbatim from RESEARCH.md "Runtime State Inventory"):**
- **96 files** get `["BLE001"]` (full list in RESEARCH.md `### Full BLE001 worklist`)
- **19 files** get `["T201"]` (full list in RESEARCH.md `### Full T201 worklist`)
- **12 intersection files** get `["BLE001", "T201"]` in one combined entry:
  `mcp_server.py`, `hosts/registry.py`, `session_parsers/_common.py`, `claude.py`,
  `cline.py`, `codex.py`, `copilot.py`, `gemini.py`, `opencode.py`,
  `benchmarks/swe/routing_replay_bench.py`, `benchmarks/swe/savings_replay.py`,
  `benchmarks/tool_bench/report.py`

**Regeneration commands** (QBL-GATE-05 — executor must re-run to verify the table matches
current source, since the worktree is dirty):
```bash
uv run ruff check src --select BLE001 --output-format=concise | grep -oE "^src/[^:]+" | sort -u
uv run ruff check src --select T20    --output-format=concise | grep -oE "^src/[^:]+" | sort -u
```

**Critical:** Do NOT add `BLE001`/`T201` to the top-level `ignore` list — that disables them
everywhere and lets new debt slip through (Pitfall 3, QBL-GATE-02).

---

### `Makefile` — `test-full` target (config / build-tooling, batch)

**Analog:** existing `test-cov` target (`Makefile` lines 92-93) and `test` target (lines 82-87).

**`test-cov` (the closest analog — coverage invocation idiom)** (lines 92-93):
```makefile
test-cov: ## Run tests with terminal and HTML coverage reports
	uv run pytest --cov=atelier --cov-report=term-missing --cov-report=html
```
> ⚠️ This analog inherits the `addopts = -m 'not slow'` default (pyproject line 116), so it
> measures coverage **without** the 87 slow tests. The new target must override that marker
> filter (Pitfall 2).

**`test` (the slow-inclusive + parallel idiom)** (lines 82-87):
```makefile
test: | _ensure_hooks ## Run all tests
	@bash -lc 'if uv run python -c "import xdist" >/dev/null 2>&1; then uv run pytest -q -ra --durations=0 -n auto --dist=loadfile; else uv run pytest -q -ra --durations=0; fi'
```

**Conventions to copy:**
- `uv run pytest ...` prefix (every test target uses it)
- `## <description>` inline doc comment (consumed by the `help` target, lines 170-172)
- `.PHONY` registration — add `test-full` to the `.PHONY` line (lines 11-14)
- Optional `| _ensure_hooks` order-only prereq if the target should ensure git hooks

**Target pattern (from RESEARCH.md Pattern 3):**
```makefile
test-full: ## Run the FULL suite (incl. slow) with coverage floor
	uv run pytest -m "" --cov=atelier --cov-report=term-missing \
		--cov-fail-under=$(COV_FAIL_UNDER)
```
- `-m ""` clears the `addopts` marker filter to include slow tests. **Verify at execution**
  that this collects 2088 (not 2001); if pytest merges instead of overriding, use
  `--override-ini "addopts=..."` (Pitfall 2 / Assumption A1).
- `$(COV_FAIL_UNDER)` follows the existing `VAR ?= default` convention (e.g.,
  `ATELIER_STORE ?=` line 4, `TEST_PRINT_TIME ?=` line 6). Define
  `COV_FAIL_UNDER ?= <measured-floor>` near the top of the Makefile.

---

### `.github/workflows/nightly-coverage.yml` — scheduled coverage workflow (CI, event-driven)

**Primary analog:** `.github/workflows/docs-governance.yml` — **already uses
`schedule.cron` + `workflow_dispatch`**, the exact trigger combination this phase needs.
**Secondary analog:** `tests.yml` `test` job — for the uv/test step idioms.

**Trigger + permissions + defaults pattern (copy verbatim from `docs-governance.yml` lines 3-21):**
```yaml
on:
  pull_request:
    branches:
      - main
  push:
    branches:
      - main
  schedule:
    - cron: "25 3 * * *"
  workflow_dispatch:

permissions:
  contents: read

defaults:
  run:
    shell: bash
```
> For the nightly job, drop the `pull_request`/`push` triggers (keep only `schedule` +
> `workflow_dispatch`). Keep `permissions: contents: read` (least privilege — Security
> Domain V14). Use a distinct cron minute (e.g. `"0 7 * * *"`) so it does not collide with
> docs-governance's `"25 3 * * *"`.

**Job + steps pattern (copy from `docs-governance.yml` lines 23-44 / `tests.yml` lines 100-129):**
```yaml
jobs:
  coverage:
    name: Nightly coverage
    runs-on: ubuntu-latest
    timeout-minutes: 40        # full suite incl. slow > tests.yml's 20m PR budget (Pitfall 5)

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --frozen --group dev

      - name: Run full-suite coverage
        run: make test-full
```

**Conventions to copy (verified across all 3 existing workflows):**
- Action pins: `actions/checkout@v4`, `actions/setup-python@v5`, `astral-sh/setup-uv@v5`
- `enable-cache: true` on setup-uv
- `uv sync --frozen --group dev` install step (frozen against `uv.lock` — Security V14)
- Named steps with `name:` keys (every step in every workflow is named)
- `runs-on: ubuntu-latest`, explicit `timeout-minutes`

**Validation (Pitfall 4):**
```bash
uv run python -c "import yaml; d=yaml.safe_load(open('.github/workflows/nightly-coverage.yml')); assert 'schedule' in d.get('on', d.get(True, {}))"
```

## Shared Patterns

### Scoped rule relaxation (NOT blanket disable)
**Source:** `pyproject.toml` `[[tool.mypy.overrides]]` (lines 129-140)
**Apply to:** the new `[tool.ruff.lint.per-file-ignores]` table
The repo's established convention is to keep a rule globally enabled and relax it for a
named list of modules — never to disable it project-wide. Ruff per-file-ignores mirrors the
existing mypy-overrides pattern exactly.

### uv-based CI step block
**Source:** `tests.yml` lines 53-67 / `docs-governance.yml` lines 27-41
**Apply to:** every job in `nightly-coverage.yml`
```yaml
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --frozen --group dev
```

### Makefile target documentation convention
**Source:** `Makefile` lines 92-99, help target lines 170-172
**Apply to:** the new `test-full` target
Every target carries a `## description` comment and is listed in `.PHONY`. The `help` target
greps `## ` to auto-generate usage — so the comment is load-bearing, not decorative.

### CI invokes Makefile targets, not raw commands
**Source:** `tests.yml` (`run: make lint`, `run: make test`), `docs-governance.yml` (`run: make docs-check`)
**Apply to:** `nightly-coverage.yml` (`run: make test-full`)
All CI jobs delegate to Makefile targets so local and CI behavior stay identical. The nightly
workflow must call `make test-full`, not inline pytest flags.

## No Analog Found

None. All three change surfaces have exact in-repo precedents:

| File | Role | Why no gap |
|------|------|------------|
| `pyproject.toml` | config | Existing ruff/mypy tables provide the scoped-relaxation pattern. |
| `Makefile` | build-tooling | Existing `test-cov`/`test` targets provide the coverage + slow-inclusive idioms. |
| `nightly-coverage.yml` | CI | `docs-governance.yml` already implements schedule+dispatch; `tests.yml` provides uv/test steps. |

## Metadata

**Analog search scope:** repo root (`pyproject.toml`, `Makefile`), `.github/workflows/`
**Files scanned:** `pyproject.toml`, `Makefile`, `.github/workflows/tests.yml`,
`.github/workflows/docs-governance.yml`, `.github/workflows/release.yml`, `22-RESEARCH.md`,
`ROADMAP.md`
**Pattern extraction date:** 2026-05-29
