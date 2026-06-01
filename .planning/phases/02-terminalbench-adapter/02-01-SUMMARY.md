---
phase: 02-terminalbench-adapter
plan: "01"
subsystem: benchmarks
tags: [terminalbench, python312, pydantic, uv, benchmark-infra]
dependency_graph:
  requires: []
  provides:
    - benchmarks/pyproject.toml (standalone uv Python 3.12 project)
    - benchmarks/terminalbench/__init__.py (package marker)
    - benchmarks/terminalbench/tasks.yaml (10 pinned task IDs)
    - benchmarks/terminalbench/_env.py (configure_benchmark_runtime)
    - benchmarks/terminalbench/harness.py (TaskSpec, RunConfig, load_tasks)
  affects:
    - Wave 2 (adapter + runner) imports from these files
tech_stack:
  added:
    - terminal-bench==0.2.18 (Python 3.12 venv only)
    - hatchling (build backend for benchmarks project)
  patterns:
    - Standalone uv project (not workspace member) via [tool.uv.sources] for local path dep
    - Pydantic v2 ConfigDict(extra="forbid") for strict YAML validation
key_files:
  created:
    - benchmarks/pyproject.toml
    - benchmarks/.python-version
    - benchmarks/uv.lock
    - benchmarks/terminalbench/__init__.py
    - benchmarks/terminalbench/tasks.yaml
    - benchmarks/terminalbench/_env.py
    - benchmarks/terminalbench/harness.py
  modified: []
decisions:
  - Use [tool.uv.sources] with path = "../" editable instead of "atelier @ file://../" in dependencies (file:// requires absolute paths; [tool.uv.sources] is the uv-native way to declare local path deps)
  - Add [tool.hatch.metadata] allow-direct-references = true (hatchling requires this for any direct-reference dep, even when managed via uv.sources)
metrics:
  duration: "~3 minutes"
  completed: "2026-05-28T17:12:47Z"
  tasks_completed: 3
  tasks_total: 3
  files_created: 7
  files_modified: 0
---

# Phase 2 Plan 01: TerminalBench Benchmarks Foundation Summary

Standalone Python 3.12 uv project in `benchmarks/` with terminal-bench==0.2.18, 10 pinned task IDs in tasks.yaml, env isolation helper, and Pydantic v2 config models — foundation for Wave 2 adapter and runner.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| T1 | Create benchmarks/pyproject.toml + .python-version | `6791cf1` |
| T2 | Create terminalbench package skeleton + tasks.yaml | `4d05c4c` |
| T3 | Create _env.py + harness.py data models | `e8b6cb8` |

## Verification Results

All 6 success criteria passed:

1. ✅ `cd benchmarks && uv run python -c "import terminal_bench"` exits 0 using Python 3.12.10
2. ✅ `benchmarks/terminalbench/tasks.yaml` has exactly 10 pinned task IDs
3. ✅ `from terminalbench.harness import TaskSpec, RunConfig, load_tasks` imports without error
4. ✅ `configure_benchmark_runtime()` sets ATELIER_ROOT + TERMINALBENCH_OUTPUT_DIR, strips IDE vars
5. ✅ Root project venv unmodified — Python 3.11.12, terminal-bench NOT in root venv
6. ✅ `from atelier.bench.mode import make_arm_env` succeeds from benchmarks/ dir

terminal-bench version confirmed via `importlib.metadata.version('terminal-bench') == '0.2.18'` (module does not expose `__version__` attribute directly).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed hatchling direct-reference error for local path dep**
- **Found during:** Task 1 (first `uv sync`)
- **Issue:** `atelier @ file://../` caused `ValueError: Dependency #7 cannot be a direct reference unless tool.hatch.metadata.allow-direct-references is set to true`
- **Fix:** Added `[tool.hatch.metadata] allow-direct-references = true` to pyproject.toml
- **Files modified:** benchmarks/pyproject.toml

**2. [Rule 1 - Bug] Fixed relative file:// URL format**
- **Found during:** Task 1 (second `uv sync` attempt)
- **Issue:** `file://../` is invalid — `file://` scheme requires absolute URLs; uv rejected with `relative path without a working directory`
- **Fix:** Moved atelier dep out of `[project.dependencies]` and used `[tool.uv.sources]` with `atelier = { path = "../", editable = true }` — the uv-native way to declare local editable path dependencies
- **Files modified:** benchmarks/pyproject.toml

## Known Stubs

None — all data is wired and functional.

## Threat Surface Scan

No new network endpoints, auth paths, or trust boundary changes introduced. All threat model mitigations from plan are implemented:
- T-02-01: `ConfigDict(extra="forbid")` on TaskSpec + `yaml.safe_load` ✅
- T-02-02: `configure_benchmark_runtime()` strips CURSOR_WORKSPACE_ROOT, VSCODE_CWD, ATELIER_MEM_ROOT ✅

## Self-Check: PASSED

Files verified present:
- `benchmarks/pyproject.toml` ✅
- `benchmarks/.python-version` ✅
- `benchmarks/uv.lock` ✅
- `benchmarks/terminalbench/__init__.py` ✅
- `benchmarks/terminalbench/tasks.yaml` ✅
- `benchmarks/terminalbench/_env.py` ✅
- `benchmarks/terminalbench/harness.py` ✅

Commits verified:
- `6791cf1` (T1) ✅
- `4d05c4c` (T2) ✅
- `e8b6cb8` (T3) ✅
