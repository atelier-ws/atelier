# Phase 2: TerminalBench Adapter — Pattern Map

**Mapped:** 2025-07-16
**Files analyzed:** 8 new/modified files
**Analogs found:** 8 / 8

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `benchmarks/pyproject.toml` | config | — | `pyproject.toml` (root) | role-match (8/10) |
| `benchmarks/terminalbench/__init__.py` | config | — | `benchmarks/mcp_tools/__init__.py` | exact (10/10) |
| `benchmarks/terminalbench/_env.py` | utility | request-response | `benchmarks/mcp_tools/_env.py` | exact (10/10) |
| `benchmarks/terminalbench/agent_adapter.py` | service | request-response (subprocess + JSON stream) | `src/benchmarks/swe/routing_replay_bench.py` (lines 165–211) | role-match (9/10) |
| `benchmarks/terminalbench/tasks.yaml` | config | — | `benchmarks/swe/configs/lite_20.yaml` | exact (9/10) |
| `benchmarks/terminalbench/runner.py` | service | CRUD + file-I/O | `src/benchmarks/swe/agent_runner.py` + `src/benchmarks/swe/metrics.py` | role-match (8/10) |
| `benchmarks/terminalbench/reporter.py` | utility | transform | `benchmarks/mcp_tools/reporter.py` | exact (9/10) |
| `benchmarks/terminalbench/harness.py` | service | CRUD | `src/benchmarks/swe/config.py` + `benchmarks/mcp_tools/harness.py` | role-match (8/10) |

---

## Pattern Assignments

---

### `benchmarks/pyproject.toml` (config)

**Analog:** `pyproject.toml` (root, lines 1–50)
**Match score:** 8/10 — same uv/hatch toolchain; only differences are `name`, `requires-python = ">=3.12"`, and a minimal dependency set.

**What to copy:**
```toml
[project]
name = "atelier-benchmarks-terminalbench"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6.0",
    "pydantic>=2.6",
    "tiktoken>=0.9",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]
```

**What to change:**
- `name` → `atelier-benchmarks-terminalbench`
- `requires-python` → `">=3.12"` (Phase 2 requirement)
- Dependencies: drop all Atelier runtime deps; keep only `pyyaml`, `pydantic`, `tiktoken`
- Add `atelier` as a path dependency (`{ path = "../..", editable = true }`) so `from atelier.bench.mode import make_arm_env` resolves at dev time
- No `[project.scripts]` entry needed

---

### `benchmarks/terminalbench/__init__.py` (package marker)

**Analog:** `benchmarks/mcp_tools/__init__.py` (empty, 0 bytes)
**Match score:** 10/10 — identical: empty file, makes directory a package.

**What to copy:** Empty file. No content needed.

---

### `benchmarks/terminalbench/_env.py` (utility, request-response)

**Analog:** `benchmarks/mcp_tools/_env.py` (all 27 lines)
**Match score:** 10/10 — direct copy with minor additions for TerminalBench isolation.

**Imports pattern** (`_env.py` lines 1–6):
```python
from __future__ import annotations

import os
from pathlib import Path
```

**Core pattern** (`_env.py` lines 9–27):
```python
def configure_benchmark_runtime(root: Path, *, workspace_root: Path | None = None) -> Path:
    """Point benchmark runtime state at a temp root while preserving file access."""
    resolved_root = root.expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    resolved_workspace = (workspace_root or resolved_root).expanduser().resolve()

    os.environ["ATELIER_ROOT"] = str(resolved_root / ".atelier")
    os.environ["ATELIER_LESSONS_ROOT"] = str(resolved_root / ".lessons")
    os.environ["ATELIER_WORKSPACE_ROOT"] = str(resolved_workspace)
    os.environ["CLAUDE_WORKSPACE_ROOT"] = str(resolved_workspace)
    os.environ.pop("CURSOR_WORKSPACE_ROOT", None)
    os.environ.pop("VSCODE_CWD", None)
    os.environ.pop("ATELIER_MEM_ROOT", None)
    return resolved_root
```

**What to change:**
- Add `TERMINALBENCH_TASK_DIR` env var pointing at the task sandbox
- No other changes needed; the pattern is already correct for isolated subprocess environments

---

### `benchmarks/terminalbench/agent_adapter.py` (service, subprocess + JSON stream)

**Analog:** `src/benchmarks/swe/routing_replay_bench.py` lines 165–211 (`_call_haiku` function)
**Match score:** 9/10 — the only existing example of `claude -p --output-format json` subprocess invocation in this codebase.

**Imports pattern** (routing_replay_bench.py lines 38–44):
```python
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
```

**Core subprocess invocation pattern** (routing_replay_bench.py lines 186–211):
```python
result = subprocess.run(
    [
        "claude",
        "--model",
        haiku_model,
        "-p",
        prompt,
        "--output-format",
        "json",              # ← Phase 2 needs "stream-json" instead
        "--no-session-persistence",
    ],
    capture_output=True,
    text=True,
    timeout=timeout,
)
data = json.loads(result.stdout)
raw = str(data.get("result", ""))
usage = data.get("usage") or {}
inp_tok = int(usage.get("cache_creation_input_tokens", 0)) + int(usage.get("input_tokens", 0))
out_tok = int(usage.get("output_tokens", 0))
```

**Error handling pattern** (routing_replay_bench.py lines 208–211):
```python
except subprocess.TimeoutExpired:
    return "", "timeout", 0, 0
except Exception as exc:
    return "", str(exc)[:200], 0, 0
```

**Env injection pattern** (`src/atelier/bench/mode.py` lines 47–61):
```python
from atelier.bench.mode import BenchMode, make_arm_env

# Build isolated env for subprocess:
env = make_arm_env(atelier_root=tmp_dir / ".atelier", mode=BenchMode.ON)
# OR for OFF arm:
env = make_arm_env(atelier_root=tmp_dir / ".atelier", mode=BenchMode.OFF)

result = subprocess.run(
    ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"],
    env=env,
    capture_output=True,
    text=True,
    timeout=timeout,
)
```

**What to change from analog:**
- Switch `--output-format json` → `--output-format stream-json --verbose` (TB-02 requirement)
- Parse NDJSON (one JSON object per line) instead of a single JSON blob:
  ```python
  # stream-json emits one JSON event per line; last line is the result summary
  lines = [l for l in result.stdout.splitlines() if l.strip()]
  events = []
  for line in lines:
      try:
          events.append(json.loads(line))
      except json.JSONDecodeError:
          continue
  # Final result line has type=="result"
  result_event = next((e for e in reversed(events) if e.get("type") == "result"), {})
  ```
- Accept `BenchMode` parameter; pass `env=make_arm_env(root, mode=mode)` to subprocess
- Return a structured `AdapterResult` dataclass (transcript events, token counts, latency_ms, cost_usd)
- Keep `capture_output=True, text=True` and the `subprocess.TimeoutExpired` handler

**New dataclass to introduce** (modelled after `src/benchmarks/swe/agent_runner.py` lines 22–38):
```python
@dataclass
class AdapterResult:
    task_id: str
    mode: str                    # "on" | "off"
    transcript: list[dict]       # all stream-json events
    tokens_input: int
    tokens_output: int
    cost_usd: float
    latency_ms: float
    grader_verdict: str | None   # "pass" | "fail" | None
    error: str | None = None
```

---

### `benchmarks/terminalbench/tasks.yaml` (config, pinned task list)

**Analog:** `benchmarks/swe/configs/lite_20.yaml` (all 16 lines)
**Match score:** 9/10 — same YAML flat-mapping style loaded by pydantic via `yaml.safe_load`.

**Structure to copy** (`benchmarks/swe/configs/lite_20.yaml`):
```yaml
dataset_name: swe_bench_lite
split: dev
task_limit: 20
agent_host: mock
model: mock-1
modes:
  - vanilla
  - atelier_forced_workflow
  - atelier_full_runtime
attempts_per_task: 1
max_turns: 20
max_cost_usd: 2.0
timeout_seconds: 600
output_dir: benchmarks/swe/outputs/lite_20
seed: 7
```

**What to change:**
```yaml
# benchmarks/terminalbench/tasks.yaml
version: "1"
description: "10 TerminalBench code-editing tasks under 30 min"
timeout_seconds: 1800          # 30 min ceiling per task
tasks:
  - id: tb_edit_001             # replace with real TB task IDs
    description: "..."
    category: code_editing
  - id: tb_edit_002
    # ... 9 more
```
- Use a list-of-mappings shape (each task has `id`, `description`, `category`)
- Loaded via `yaml.safe_load()` exactly as in `src/benchmarks/swe/config.py` line 63

---

### `benchmarks/terminalbench/runner.py` (service, CRUD + file-I/O)

**Primary analog:** `src/benchmarks/swe/agent_runner.py` (all 179 lines) — AgentResult + run loop
**Secondary analog:** `src/benchmarks/swe/metrics.py` (all 129 lines) — RunMetrics + JSONL writer
**Match score:** 8/10 — same pattern: iterate tasks × modes, call adapter, write JSONL per run.

**Imports pattern** (agent_runner.py lines 1–19):
```python
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
```

**Per-run result dataclass** (agent_runner.py lines 22–38 + metrics.py lines 12–52):
```python
@dataclass
class RunRecord:
    """One row per (task_id, mode, attempt). Written as JSONL."""
    task_id: str
    mode: str
    attempt: int
    transcript: list[dict]          # full stream-json events (TB-04)
    tokens_input: int
    tokens_output: int
    latency_ms: float
    cost_usd: float
    grader_verdict: str | None
    error: str | None = None

    def to_jsonl(self) -> str:
        import json
        return json.dumps(self.__dict__, default=str)
```

**JSONL writer** (metrics.py lines 57–63):
```python
def write_records(rows: list[RunRecord], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(r.to_jsonl())
            f.write("\n")
    return path
```

**Run loop** (agent_runner.py lines 146–149 as template):
```python
def run_task(task: TaskSpec, mode: BenchMode, cfg: RunConfig) -> RunRecord:
    t0 = time.perf_counter()
    result = adapter.invoke(task, mode=mode, timeout=cfg.timeout_seconds)
    latency_ms = (time.perf_counter() - t0) * 1000
    # write transcript + build RunRecord
```

**CLI entry-point pattern** (benchmarks/swe/make_preds.py lines 40–52):
```python
def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["on", "off"], required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tasks", default="benchmarks/terminalbench/tasks.yaml")
    args = parser.parse_args()
    # ...

if __name__ == "__main__":
    main()
```

**What to change:**
- Replace `AgentResult.patch` with `AdapterResult.transcript` (list of stream-json events)
- Replace SWE modes with `BenchMode.ON / BenchMode.OFF` from `atelier.bench.mode`
- Add `--mode on|off` CLI flag (TB-05 requirement — produces distinguishably different transcripts)
- Transcript files written as `outputs/{task_id}_{mode}_{attempt}.json` (pretty-printed JSON for readability, JSONL for aggregation)
- Call `make_arm_env(root, mode=BenchMode.ON/OFF)` and pass to `agent_adapter.invoke()`

---

### `benchmarks/terminalbench/reporter.py` (utility, transform)

**Analog:** `benchmarks/mcp_tools/reporter.py` (all 94 lines)
**Match score:** 9/10 — same ANSI terminal output pattern; swap token-savings columns for TB metrics (latency, cost, verdict).

**Imports + colour constants** (reporter.py lines 1–12):
```python
from __future__ import annotations

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_DIM = "\033[2m"
```

**Report render pattern** (reporter.py lines 25–70):
```python
def render_tool_report(report: ToolReport) -> str:
    lines: list[str] = []
    status_color = _GREEN if report.failed == 0 else _RED
    lines.append(
        f"\n{_BOLD}{_CYAN}● {report.tool_name}{_RESET}  "
        f"{status_color}{report.passed}/{report.total} passed{_RESET}"
    )
    # Column headers + per-result rows
    for r in report.results:
        status = _pass_fail(r.passed)
        lines.append(f"  {r.case.label:<36} {status} ...")
    return "\n".join(lines)
```

**Summary pattern** (reporter.py lines 73–94):
```python
def render_summary(reports: list[ToolReport]) -> str:
    lines: list[str] = []
    lines.append(f"\n{_BOLD}━━ Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{_RESET}")
    for report in reports:
        lines.append(render_tool_report(report))
    # aggregate totals
    return "\n".join(lines)
```

**What to change:**
- Input type: `list[RunRecord]` grouped by mode (ON vs OFF) instead of `ToolReport`
- Columns: `task_id`, `mode`, `verdict`, `latency_ms`, `tokens_in`, `tokens_out`, `cost_usd`
- Add a **mode comparison** section at the bottom: ON arm vs OFF arm delta for each task (TB-05)
- Keep the ANSI colour helpers verbatim; they are already correct

---

### `benchmarks/terminalbench/harness.py` (service, CRUD)

**Primary analog:** `src/benchmarks/swe/config.py` (all 66 lines) — pydantic YAML config loader
**Secondary analog:** `benchmarks/mcp_tools/harness.py` lines 22–54 — `BenchCase` dataclass
**Match score:** 8/10

**YAML config loader pattern** (config.py lines 1–66):
```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BenchConfig(BaseModel):
    """Strict YAML schema for a SWE-bench harness run."""
    model_config = ConfigDict(extra="forbid")

    dataset_name: str = "swe_bench_lite"
    task_limit: int = Field(default=20, ge=1)
    # ...


def load_config(path: str | Path) -> BenchConfig:
    """Load and validate a benchmark YAML file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"config not found: {p}")
    raw = yaml.safe_load(p.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a YAML mapping, got {type(raw).__name__}")
    return BenchConfig(**raw)
```

**Task dataclass pattern** (harness.py lines 22–53):
```python
@dataclass
class BenchCase:
    op: str
    args: dict[str, Any]
    assert_keys: list[str] = field(default_factory=list)
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.op
```

**What to change:**
- Replace `BenchCase` with a `TaskSpec` pydantic model (id, description, category, timeout_seconds)
- Load tasks from YAML list-of-mappings (`tasks.yaml`) using `yaml.safe_load` + pydantic validation
- Add `RunConfig` pydantic model: `timeout_seconds`, `output_dir`, `attempts_per_task`
- No `assert_keys` / `baseline_tokens` — TerminalBench uses grader verdict, not token-savings check

**New models to introduce:**
```python
class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str = ""
    category: str = "code_editing"
    timeout_seconds: int = Field(default=1800, ge=60)

class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks_path: str = "benchmarks/terminalbench/tasks.yaml"
    output_dir: str = "benchmarks/terminalbench/outputs"
    attempts_per_task: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=1800, ge=60)

def load_tasks(path: str | Path) -> list[TaskSpec]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return [TaskSpec(**t) for t in raw.get("tasks", [])]
```

---

## Shared Patterns

### subprocess invocation (apply to `agent_adapter.py`)
**Source:** `src/benchmarks/swe/routing_replay_bench.py` lines 186–211

```python
result = subprocess.run(
    ["claude", "--model", model, "-p", prompt,
     "--output-format", "stream-json", "--verbose",
     "--no-session-persistence"],
    capture_output=True,
    text=True,
    timeout=timeout,
    env=env,          # always pass explicit env from make_arm_env()
)
```

Key invariants from existing code:
- `capture_output=True, text=True` — always
- `timeout=` — always present; catch `subprocess.TimeoutExpired`
- `env=` — always built from `make_arm_env(root, mode=...)` to isolate `ATELIER_ROOT`

---

### BenchMode / make_arm_env (apply to `runner.py` and `agent_adapter.py`)
**Source:** `src/atelier/bench/mode.py` lines 47–61

```python
from atelier.bench.mode import BenchMode, make_arm_env

# ON arm
env_on  = make_arm_env(atelier_root / "on",  mode=BenchMode.ON)
# OFF arm
env_off = make_arm_env(atelier_root / "off", mode=BenchMode.OFF)
```

The returned dict is a full `os.environ` copy with `ATELIER_ROOT` and `ATELIER_BENCH_MODE` overridden. Pass directly as `env=` to `subprocess.run`.

---

### Pydantic YAML config loading (apply to `harness.py`)
**Source:** `src/benchmarks/swe/config.py` lines 58–66

```python
def load_config(path: str | Path) -> BenchConfig:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"config not found: {p}")
    raw = yaml.safe_load(p.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a YAML mapping, got {type(raw).__name__}")
    return BenchConfig(**raw)
```

Use `ConfigDict(extra="forbid")` on every pydantic model so a typo in `tasks.yaml` fails fast.

---

### JSONL run-record writer (apply to `runner.py`)
**Source:** `src/benchmarks/swe/metrics.py` lines 57–63

```python
def write_records(rows: list[RunRecord], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(r.to_jsonl() + "\n")
    return path
```

---

### ANSI terminal colours (apply to `reporter.py`)
**Source:** `benchmarks/mcp_tools/reporter.py` lines 7–13

```python
_GREEN = "\033[32m"
_RED   = "\033[31m"
_CYAN  = "\033[36m"
_BOLD  = "\033[1m"
_RESET = "\033[0m"
_DIM   = "\033[2m"
```

Copy verbatim; do not add a rich/click dependency — the existing pattern avoids it.

---

### configure_benchmark_runtime (apply to `_env.py`)
**Source:** `benchmarks/mcp_tools/_env.py` lines 9–27

Copy verbatim. The function sets `ATELIER_ROOT`, `ATELIER_LESSONS_ROOT`, `ATELIER_WORKSPACE_ROOT`, and `CLAUDE_WORKSPACE_ROOT`, and strips Cursor/VSCode pollution. TerminalBench needs these same env-var guards so the `claude -p` subprocess does not accidentally pick up IDE state from the outer shell.

---

## No Analog Found

All 8 files have analogs. The only truly new logic (not covered by existing patterns) is:

| Logic | Gap | Resolution |
|-------|-----|------------|
| NDJSON stream-json line parsing | No existing NDJSON parser in codebase | Use simple `for line in stdout.splitlines(): json.loads(line)` loop; no new library needed |
| TerminalBench grader integration | No grader call exists | Stub as `grader_verdict: str \| None = None`; populated by external `tb grade` CLI call after run |
| `--mode on\|off` CLI flag | mcp_tools bench has no CLI entry point | Copy `argparse` pattern from `benchmarks/swe/make_preds.py` lines 40–52 |

---

## Metadata

**Analog search scope:** `benchmarks/`, `src/benchmarks/`, `src/atelier/bench/`
**Files scanned:** 18
**Pattern extraction date:** 2025-07-16
