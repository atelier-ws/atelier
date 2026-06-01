# Phase 2: TerminalBench Adapter — Research

**Researched:** 2026-06-09
**Domain:** TerminalBench integration, `claude -p` subprocess API, uv isolated workspace, per-run transcript schema
**Confidence:** HIGH — verified via live codebase inspection, terminal-bench package introspection, live `claude -p` output from prior research, and registry fetch

---

## Summary

Phase 2 wires TerminalBench into a standalone `benchmarks/terminalbench/` package that can run 10 pinned code-editing tasks under both bench modes and produce a fully-populated transcript JSON per run.

**TerminalBench is already installed** on the system at Python 3.13 (`/home/pankaj/.local/lib/python3.13/site-packages/terminal_bench/`) at version `0.2.18`. Python 3.12.10 is available via uv managed Pythons. The `benchmarks/pyproject.toml` must be a **standalone uv project** (not a workspace member) with `requires-python = ">=3.12"` and a `.python-version` file pinning to `3.12`. Docker is running — `docker ps` confirms the daemon is live.

The agent adapter subclasses `AbstractInstalledAgent` from `terminal_bench.agents.installed_agents.abstract_installed_agent`. It installs `claude-code` inside the Docker container (via a setup script) and runs `claude --verbose --output-format stream-json -p ...` piped through `tee /agent-logs/stream.jsonl`. After `Harness.run()`, the per-trial transcript JSON is assembled by combining: (a) TerminalBench's `TrialResults.is_resolved` for grader verdict, and (b) the `result` line parsed from `stream.jsonl` for all token/cost/latency fields.

**Primary recommendation:** Subclass `AbstractInstalledAgent`, override `_run_agent_commands` to pipe to `/agent-logs/stream.jsonl`, and post-process the harness output to assemble the full transcript JSON. Do NOT attempt to parse tokens inside `perform_task` — the current `AbstractInstalledAgent.perform_task` returns `AgentResult(total_input_tokens=0, total_output_tokens=0)` by design; accurate counts come from the stream-json file.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TB-01 | `benchmarks/terminalbench/` package installs via isolated `benchmarks/pyproject.toml` (Python 3.12) | Standalone uv project pattern; Python 3.12.10 available via uv |
| TB-02 | `agent_adapter.py` invokes `claude -p --output-format stream-json --verbose` subprocess, parses result line | `AbstractInstalledAgent._run_agent_commands` pattern + tee-to-file strategy documented here |
| TB-03 | `tasks.yaml` pins 10 TerminalBench task IDs completing in <30 min, code-editing focused | 10 tasks selected from `terminal-bench-core 0.1.1` registry fetch |
| TB-04 | Runner produces per-run transcript JSON with all fields populated | Schema derived from stream-json result line + TrialResults model |
| TB-05 | `--mode on` vs `--mode off` arms produce distinguishably different transcripts | `make_arm_env(mode)` from Phase 1 propagates to subprocess env; ATELIER_BENCH_MODE controls routing/compaction/memory |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Docker container lifecycle | TerminalBench `Harness` | — | Harness owns container spin-up, task mounting, tmux session, grader execution |
| Agent installation in container | `AtelierClaudeAgent._install_agent_script_path` | `AbstractInstalledAgent` base | Setup script installs `claude-code` npm package inside the container |
| Claude invocation + stream-json capture | `AtelierClaudeAgent._run_agent_commands` | Container tmux session | Command string runs inside Docker; `tee /agent-logs/stream.jsonl` captures output |
| Stream-json result parsing | `agent_adapter.py:_parse_stream_jsonl()` | — | Host-side post-processing after harness.run() |
| Grader verdict | TerminalBench `TrialResults.is_resolved` | `run-tests.sh` inside container | TerminalBench runs pytest inside the container; result propagated as `is_resolved` |
| Arm environment isolation | `atelier.bench.make_arm_env(mode)` (Phase 1) | — | Returns env dict with isolated `ATELIER_ROOT` + `ATELIER_BENCH_MODE` |
| Token/cost/latency fields | `result` line in `stream.jsonl` | — | Authoritative source; NOT TerminalBench's `AgentResult` (which returns 0s) |
| Task selection | `benchmarks/terminalbench/tasks.yaml` | `terminal_bench.dataset.Dataset` | YAML pins 10 task IDs; Dataset API accepts `task_ids: list[str]` |
| Workspace isolation (Python 3.12) | `benchmarks/pyproject.toml` standalone project | `uv run --project benchmarks/` | Separate Python version from main project |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `terminal-bench` | `0.2.18` [VERIFIED: pip index versions] | TerminalBench harness: Docker task execution, grading, `Harness`/`BaseAgent`/`BenchmarkResults` | Named by developers in project requirements; official PyPI release |
| `pydantic` | `>=2.6` (from root) | Data models for transcript schema | Already in root deps; used throughout atelier |
| `click` | `>=8.1` (from root) | CLI entry points | Already in root deps |
| `pyyaml` | `>=6.0` (from root) | Parse `tasks.yaml` | Already in root deps |
| `rich` | `>=13.7` (from root) | Progress display | Already in root deps |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `jinja2` | `>=3.1` | Setup script templating (matches `ClaudeCodeAgent` pattern) | Render install script template with agent version |
| `atelier` (main package) | `>=0.2.0` | Import `atelier.bench.make_arm_env` for arm isolation | TB-05 arm mode injection |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `AbstractInstalledAgent` subclass | `BaseAgent` direct subclass | AbstractInstalledAgent manages install script, env setup, and tmux command execution; BaseAgent requires more manual container interaction |
| Standalone pyproject.toml | uv workspace member | Workspace member would unify deps and potentially conflict with Python 3.11 root; standalone is cleaner |
| Tee to `/agent-logs/stream.jsonl` | Capture tmux pane output | Pane capture is lossy for long outputs; tee to mounted volume is reliable |

**Installation (benchmarks workspace):**
```bash
# Create standalone project (run once from repo root):
uv init benchmarks --no-workspace --python 3.12
# Then install deps:
cd benchmarks && uv add terminal-bench==0.2.18 pyyaml rich click pydantic
```

---

## Package Legitimacy Audit

| Package | Registry | Age | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|
| `terminal-bench` | PyPI | ~1 yr (v0.1.0 initial) | `[OK]` (no source repo linked — noted) | Approved; used in published research |
| `pydantic` | PyPI | ~10 yrs | `[OK]` | Approved |
| `click` | PyPI | ~10 yrs | `[OK]` | Approved |
| `pyyaml` | PyPI | ~15 yrs | `[OK]` | Approved |
| `rich` | PyPI | ~5 yrs | `[OK]` | Approved |

*slopcheck was available and run (`/home/pankaj/.local/bin/slopcheck`). All packages passed `[OK]`.*

**Packages removed due to [SLOP]:** none
**Packages flagged [SUS]:** none

> Note: `terminal-bench` has no source repository linked in its PyPI metadata. The package
> is maintained by the Laude Institute (laude-institute/terminal-bench on GitHub). The
> `RegistryClient.DEFAULT_REGISTRY_URL` in the installed wheel points to
> `https://raw.githubusercontent.com/laude-institute/terminal-bench/main/registry.json`
> which confirms GitHub provenance. [VERIFIED: live package inspection]

---

## Architecture Patterns

### System Architecture Diagram

```
tasks.yaml (10 pinned IDs)
        │
        ▼
terminal_bench.dataset.Dataset(task_ids=[...])
        │
        ▼ task instruction text
AtelierClaudeAgent (AbstractInstalledAgent subclass)
        │
        ├── _env: {ANTHROPIC_API_KEY, ATELIER_BENCH_MODE=on|off, ATELIER_ROOT=<tmp>}
        │         ◄── make_arm_env(mode) from atelier.bench (Phase 1)
        │
        ├── _install_agent_script_path: renders claude-code setup.sh.j2
        │
        └── _run_agent_commands(instruction):
              "claude --verbose --output-format stream-json -p '<instruction>'
               --allowedTools Bash Edit Write Read Glob Grep LS
               --dangerously-skip-permissions
               2>&1 | tee /agent-logs/stream.jsonl"
                      │
                      ▼ (inside Docker container via tmux)
             Harness.run() orchestrates:
               1. Docker container spin-up
               2. Agent install script
               3. tmux command execution
               4. pytest grader in container
                      │
                      ▼ TrialResults (is_resolved, trial_started/ended_at)
         host-side: <output_path>/<task>/<trial>/agent-logs/stream.jsonl
                      │
                      ▼ _parse_stream_jsonl()
         {input_tokens, output_tokens, cache_*_tokens, total_cost_usd, duration_ms}
                      │
                      ▼
         Transcript JSON (TB-04 schema) written atomically via os.replace()
```

### Recommended Project Structure
```
benchmarks/
├── pyproject.toml           # standalone uv project, requires-python=">=3.12"
├── .python-version          # "3.12" — pins uv to use Python 3.12.10
├── uv.lock                  # generated lock file for reproducibility
└── terminalbench/
    ├── __init__.py
    ├── agent_adapter.py     # AtelierClaudeAgent + run_terminalbench_trial()
    ├── grader.py            # thin wrapper around TrialResults.is_resolved
    ├── runner.py            # CLI: --task-id --mode --rep --out
    └── tasks.yaml           # 10 pinned task IDs
```

### Pattern 1: AtelierClaudeAgent (AbstractInstalledAgent subclass)

**What:** Runs `claude-code` inside TerminalBench Docker containers with mode-specific env
**When to use:** All TerminalBench trials; both on/off arms

```python
# Source: live inspection of terminal_bench.agents.installed_agents.claude_code_agent
# and terminal_bench.agents.installed_agents.abstract_installed_agent
import os
import shlex
from pathlib import Path
from terminal_bench.agents.installed_agents.abstract_installed_agent import AbstractInstalledAgent
from terminal_bench.terminal.models import TerminalCommand

CONTAINER_STREAM_LOG = "/agent-logs/stream.jsonl"

class AtelierClaudeAgent(AbstractInstalledAgent):
    """Claude Code agent with Atelier bench-mode injection."""

    def __init__(self, bench_mode: str = "on", model: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._bench_mode = bench_mode  # "on" or "off"
        self._model = model

    @staticmethod
    def name() -> str:
        return "atelier-claude"

    @property
    def _env(self) -> dict[str, str]:
        # make_arm_env returns {**os.environ, ATELIER_ROOT=<tmp>, ATELIER_BENCH_MODE=on|off}
        # We extract only the keys needed inside Docker (not full host env)
        env: dict[str, str] = {
            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            "ATELIER_BENCH_MODE": self._bench_mode,
            "FORCE_AUTO_BACKGROUND_TASKS": "1",
        }
        if self._model:
            env["ANTHROPIC_MODEL"] = self._model
        elif "ANTHROPIC_MODEL" in os.environ:
            env["ANTHROPIC_MODEL"] = os.environ["ANTHROPIC_MODEL"]
        # Explicitly unset to prevent dev-mode contamination (see PITFALLS #3b)
        # ATELIER_DEV_MODE must NOT be passed through to the container
        return env

    @property
    def _install_agent_script_path(self) -> Path:
        # Uses templated setup.sh.j2 — same pattern as ClaudeCodeAgent
        return self._get_templated_script_path("setup.sh.j2")

    def _run_agent_commands(self, instruction: str) -> list[TerminalCommand]:
        escaped = shlex.quote(instruction)
        allowed = "Bash Edit Write Read Glob Grep LS"
        # Tee to /agent-logs/stream.jsonl (volume-mounted path, accessible from host)
        cmd = (
            f"claude --verbose --output-format stream-json "
            f"-p {escaped} "
            f"--allowedTools {allowed} "
            f"--dangerously-skip-permissions "
            f"2>&1 | tee {CONTAINER_STREAM_LOG}"
        )
        return [TerminalCommand(
            command=cmd,
            min_timeout_sec=0.0,
            max_timeout_sec=float("inf"),
            block=True,
            append_enter=True,
        )]
```

### Pattern 2: Stream-JSON Result Line Parsing

**What:** Extracts token/cost/latency fields from the tee'd stream.jsonl file
**When to use:** After every TerminalBench trial, host-side post-processing

```python
# Source: live claude -p run captured in .planning/research/STACK.md (2026-05-28)
import json
from pathlib import Path

def parse_stream_jsonl(log_path: Path) -> dict:
    """Parse the claude --output-format stream-json log for the result line.

    The result line has type='result' and contains total_cost_usd, duration_ms,
    duration_api_ms, and usage.{input_tokens, output_tokens, cache_*_tokens}.
    """
    result_line: dict | None = None
    for raw_line in log_path.read_text().splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
            if obj.get("type") == "result":
                result_line = obj
        except json.JSONDecodeError:
            pass

    if result_line is None:
        return {"error": "no_result_line"}

    u = result_line.get("usage", {})
    return {
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": u.get("cache_read_input_tokens", 0),
        "total_cost_usd": result_line.get("total_cost_usd", 0.0),
        "duration_ms": result_line.get("duration_ms", 0),
        "duration_api_ms": result_line.get("duration_api_ms", 0),
        "num_turns": result_line.get("num_turns", 0),
        "is_error": result_line.get("is_error", False),
        "stop_reason": result_line.get("stop_reason", ""),
    }
```

**Example `result` line** (from live `claude -p` run, 2026-05-28) [VERIFIED: STACK.md]:
```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "duration_ms": 3557,
  "duration_api_ms": 2104,
  "num_turns": 1,
  "result": "Two",
  "stop_reason": "end_turn",
  "total_cost_usd": 0.15264875,
  "usage": {
    "input_tokens": 6,
    "cache_creation_input_tokens": 24395,
    "cache_read_input_tokens": 0,
    "output_tokens": 6,
    "iterations": [{"input_tokens": 6, "output_tokens": 6}]
  },
  "modelUsage": {
    "claude-opus-4-7": {
      "inputTokens": 6, "outputTokens": 6,
      "cacheReadInputTokens": 0,
      "cacheCreationInputTokens": 24395,
      "costUSD": 0.15264875
    }
  }
}
```

**Critical:** `--verbose` is required with `--output-format stream-json` — without it, `claude` exits with error. [VERIFIED: STACK.md live invocation]

### Pattern 3: Standalone uv Workspace Setup

**What:** Independent `benchmarks/pyproject.toml` that uses Python 3.12 without polluting root
**When to use:** Phase 2 setup (one-time)

```toml
# benchmarks/pyproject.toml
[project]
name = "atelier-benchmarks"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "terminal-bench==0.2.18",
    "pydantic>=2.6",
    "pyyaml>=6.0",
    "rich>=13.7",
    "click>=8.1",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

```
# benchmarks/.python-version
3.12
```

**Init command** (from repo root):
```bash
# Create standalone project — --no-workspace prevents discovery of root pyproject.toml
uv init benchmarks --no-workspace --python 3.12 --name atelier-benchmarks --package
```

**Run commands:**
```bash
# From repo root:
uv run --project benchmarks/ python -m benchmarks.terminalbench.runner --help

# Or from benchmarks/ dir:
cd benchmarks && uv run python -m terminalbench.runner --help
```

**Why NOT a uv workspace member:** The root `pyproject.toml` has `requires-python = ">=3.11"` and no `[tool.uv.workspace]` section. Adding `benchmarks/` as a workspace member would force uv to resolve a shared environment that must satisfy both Python 3.11 (root) and 3.12 (benchmarks). The standalone approach uses Python 3.12.10 from uv's managed Pythons without touching the root venv. [VERIFIED: live `uv python list`; Python 3.12.10 confirmed at `/home/pankaj/.local/share/uv/python/cpython-3.12.10-linux-x86_64-gnu/`]

### Pattern 4: Harness Integration

**What:** Instantiate TerminalBench `Harness` and run a single trial, then assemble transcript
**When to use:** `run_terminalbench_trial()` in `agent_adapter.py`

```python
# Source: live terminal_bench package inspection
from terminal_bench import Harness, BenchmarkResults
import tempfile
from pathlib import Path

def run_terminalbench_trial(
    task_id: str,
    bench_mode: str,        # "on" | "off"
    rep: int,
    out_dir: Path,
    model: str = "claude-sonnet-4-5",
    dataset_name: str = "terminal-bench-core",
    dataset_version: str = "0.1.1",
) -> dict:
    """Run one TerminalBench trial and return full transcript dict."""
    import tempfile, os
    from atelier.bench import make_arm_env, BenchMode

    # Get arm env (isolated ATELIER_ROOT for this run)
    arm_tmp = Path(tempfile.mkdtemp(prefix=f"atelier_bench_{bench_mode}_"))
    mode_enum = BenchMode.ON if bench_mode == "on" else BenchMode.OFF
    arm_env = make_arm_env(arm_tmp, mode=mode_enum)

    # Inject arm env into process env before Harness spins up Docker
    # (Docker containers inherit from process env via _env property)
    old_env = {k: os.environ.get(k) for k in arm_env}
    os.environ.update(arm_env)

    try:
        run_id = f"{task_id}__{bench_mode}__rep{rep}"
        trial_out = out_dir / run_id

        harness = Harness(
            output_path=trial_out,
            run_id=run_id,
            agent_import_path="benchmarks.terminalbench.agent_adapter.AtelierClaudeAgent",
            agent_kwargs={"bench_mode": bench_mode, "model_name": model},
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            task_ids=[task_id],
            n_attempts=1,
            n_concurrent_trials=1,
            cleanup=True,
        )
        results: BenchmarkResults = harness.run()

        # Get grader verdict from TerminalBench
        trial_result = results.results[0] if results.results else None
        is_resolved = trial_result.is_resolved if trial_result else False

        # Get cost/latency/tokens from stream.jsonl (tee'd by _run_agent_commands)
        # TerminalBench writes agent logs to: trial_out/<task>/<trial_name>/agent-logs/
        stream_files = list(trial_out.rglob("stream.jsonl"))
        parsed = parse_stream_jsonl(stream_files[0]) if stream_files else {"error": "no_stream_log"}

        # Assemble transcript
        return _build_transcript(
            task_id=task_id,
            mode=bench_mode,
            rep=rep,
            model=model,
            is_resolved=is_resolved,
            trial_result=trial_result,
            parsed=parsed,
        )
    finally:
        # Restore env
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
```

### Anti-Patterns to Avoid
- **In-process arm switching:** Never toggle `ATELIER_BENCH_MODE` and re-run in the same process — module-level singletons in `mcp_server.py` survive between calls. Each `run_terminalbench_trial()` call is already subprocess-isolated via Docker. [VERIFIED: PITFALLS.md #2]
- **Sharing ATELIER_ROOT between arms:** `make_arm_env` creates a fresh `ATELIER_ROOT` per arm. Never reuse the same tmp dir across on/off runs of the same rep. [VERIFIED: PITFALLS.md #1]
- **Using tiktoken for published token counts:** The stream-json `usage` field is authoritative. tiktoken cl100k_base has 10-30% error for Claude. [VERIFIED: PITFALLS.md #4]
- **Not setting `ATELIER_DEV_MODE=` (clear) in container env:** If `ATELIER_DEV_MODE=1` is set in the host environment, it leaks into Docker and overrides tool visibility filtering. The `_env` property must NOT forward `ATELIER_DEV_MODE`. [VERIFIED: PITFALLS.md #3b]
- **Passing the full `os.environ` to the Docker container:** Only pass specific keys in `_env`. Forwarding the entire host environment risks leaking `ATELIER_AUTO_UPDATE`, `CURSOR_WORKSPACE_ROOT`, etc.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Docker container lifecycle | Custom docker-py scripts | `terminal_bench.Harness` | Task Dockerfiles, volume mounts, tmux session management, grader execution — hundreds of lines of plumbing |
| pass@k metric calculation | Custom binomial estimator | `BenchmarkResults.pass_at_k` | Already implements the correct estimator `1 - comb(n-c,k)/comb(n,k)` |
| Grader execution | Custom pytest runner in Docker | TerminalBench's `run-tests.sh` + `TrialResults.is_resolved` | Grader runs inside the task container against the correct environment |
| Agent install in Docker | Custom npm install script | `_get_templated_script_path("setup.sh.j2")` + `AbstractInstalledAgent` base | Handles temp file creation, chmod, container copy |
| Token counting | tiktoken approximation | stream-json `usage.input_tokens` + `usage.output_tokens` | Authoritative counts from Anthropic billing API; 0% error |
| Arm env isolation | Custom env dict building | `atelier.bench.make_arm_env(root, mode=BenchMode.ON)` (Phase 1) | Already implemented; creates isolated `ATELIER_ROOT` and sets `ATELIER_BENCH_MODE` |

---

## 1. TerminalBench Integration

### Installation Approach
[VERIFIED: live pip show terminal-bench; live `tb datasets list`]

- **PyPI package**: `terminal-bench==0.2.18` (NOT a git submodule)
- **Already installed** at Python 3.13 on this machine. Must be re-installed in the Python 3.12 benchmarks workspace.
- **Python requirement**: `>=3.12` (confirmed from wheel metadata)

### Public API Surface
```python
from terminal_bench import Harness, BenchmarkResults, BaseAgent
from terminal_bench.agents.installed_agents.abstract_installed_agent import AbstractInstalledAgent
from terminal_bench.harness.models import TrialResults
from terminal_bench.terminal.models import TerminalCommand
from terminal_bench.dataset.dataset import Dataset
```

### TrialResults fields (authoritative)
```python
class TrialResults(BaseModel):
    id: UUID4
    trial_name: str
    task_id: str
    instruction: str
    is_resolved: bool | None           # grader verdict (True=pass, False=fail)
    failure_mode: FailureMode           # UNSET | AGENT_INSTALLATION_FAILED | ...
    parser_results: dict[str, UnitTestStatus] | None
    recording_path: str | None
    total_input_tokens: int | None      # WARNING: always 0 for AbstractInstalledAgent
    total_output_tokens: int | None     # WARNING: always 0 for AbstractInstalledAgent
    trial_started_at: str | None        # ISO8601
    trial_ended_at: str | None          # ISO8601
    agent_started_at: str | None
    agent_ended_at: str | None
```
**Critical:** `total_input_tokens` / `total_output_tokens` are **always 0** for `AbstractInstalledAgent` because `perform_task` returns `AgentResult(total_input_tokens=0, total_output_tokens=0)` by default. Use stream.jsonl parsing for accurate counts.

### Grader Mechanism
The grader runs `run-tests.sh` inside the Docker container after the agent finishes. `run-tests.sh` calls pytest. Results are propagated as `TrialResults.is_resolved = True|False`. The parser type is specified in `solution.yaml` (`parser_name: pytest`).

### Dataset Loading
```python
dataset = Dataset(
    name="terminal-bench-core",
    version="0.1.1",          # pinned for reproducibility
    task_ids=["hello-world", "fix-pandas-version", ...]  # from tasks.yaml
)
```
The `Dataset` class downloads and caches the dataset from GitHub (branch `dataset/terminal-bench-core/v0.1.x`, commit `91e10457`) on first use. Subsequent runs use the cache.

---

## 2. `claude -p` Subprocess Output Format

[VERIFIED: STACK.md section 3 — live `claude -p` invocation 2026-05-28]

### Complete command for benchmarks
```bash
claude --verbose --output-format stream-json \
  -p "<escaped_instruction>" \
  --allowedTools Bash Edit Write Read Glob Grep LS \
  --dangerously-skip-permissions \
  2>&1 | tee /agent-logs/stream.jsonl
```

**Flag requirements:**
- `--verbose` is **required** when using `--output-format stream-json` — omitting it causes an error
- `--dangerously-skip-permissions` is needed for automated runs (no human approval prompt)
- `2>&1` redirects stderr to stdout before tee (so the stream-json result line on stdout is not interleaved with setup messages on stderr)

### Output event types (newline-delimited JSON)
| type | Key fields | Use for |
|------|-----------|---------|
| `system` init | `model`, `tools`, `claude_code_version` | Record model name |
| `assistant` | `message.usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}` | Per-turn accumulation (not needed if reading result line) |
| **`result`** | `total_cost_usd`, `duration_ms`, `duration_api_ms`, `usage.*`, `num_turns`, `is_error` | **Primary extraction point** |

### Fields available in `result` line
```
total_cost_usd          float   Total USD cost for the entire claude session
duration_ms             int     Wall-clock time from start to end (ms)
duration_api_ms         int     API round-trip time (excludes tool execution)
num_turns               int     Number of conversation turns
is_error                bool    True if session failed
stop_reason             str     "end_turn" | "max_turns" | "error"
usage.input_tokens      int     Uncached input tokens (billed at input rate)
usage.output_tokens     int     Output tokens
usage.cache_creation_input_tokens  int  Tokens written to prompt cache
usage.cache_read_input_tokens      int  Tokens read from prompt cache
```

**Model name extraction:** Read from the `system` init event:
```python
for line in stream:
    obj = json.loads(line)
    if obj.get("type") == "system" and obj.get("subtype") == "init":
        model_name = obj.get("model", "")
        break
```

---

## 3. Isolated Workspace Setup (TB-01)

### pyproject.toml for `benchmarks/`

```toml
[project]
name = "atelier-benchmarks"
version = "0.1.0"
description = "Atelier TerminalBench A/B benchmark runner"
requires-python = ">=3.12"
dependencies = [
    "terminal-bench==0.2.18",
    "pydantic>=2.6",
    "pyyaml>=6.0",
    "rich>=13.7",
    "click>=8.1",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["terminalbench"]
```

**Critical setup files:**
```
benchmarks/
├── pyproject.toml       (above)
├── .python-version      contains "3.12"   ← pins uv to Python 3.12.10
└── uv.lock              (generated by uv lock)
```

### How to access atelier.bench from benchmarks/

The `agent_adapter.py` needs `from atelier.bench import make_arm_env`. Options:
1. **Editable install (recommended):** Add `atelier` as a dependency in benchmarks/pyproject.toml as a path dep:
   ```toml
   dependencies = [
       "atelier @ file://../",  # points to repo root pyproject.toml
       ...
   ]
   ```
   This installs the main atelier package into the 3.12 venv in editable mode.

2. **sys.path manipulation:** Less clean but works: `sys.path.insert(0, str(Path(__file__).parents[2] / "src"))` in agent_adapter.py.

Recommendation: **Option 1** (editable install via `file://` dep) — keeps imports clean and explicit.

> **Note on "workspace" terminology in TB-01:** The requirement says "Python 3.12 uv workspace" but the root `pyproject.toml` has no `[tool.uv.workspace]` section. This means a **standalone uv project** (not a workspace member) is the correct interpretation. The `--no-workspace` flag to `uv init` prevents uv from auto-discovering the root workspace config. [ASSUMED — the TB-01 phrase "workspace" likely means "separate project" in context, not a uv workspace member]

---

## 4. Transcript JSON Schema (TB-04)

The per-run transcript JSON for a single trial (one `(task_id, mode, rep)` cell):

```json
{
  "task_id": "swe-bench-fsspec",
  "mode": "on",
  "rep": 1,
  "model": "claude-sonnet-4-5",

  "input_tokens": 12450,
  "output_tokens": 834,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 8200,
  "latency_ms": 42300,
  "latency_api_ms": 38100,
  "num_turns": 7,
  "cost_usd": 0.0872,

  "grader_verdict": "pass",
  "grader_is_resolved": true,
  "grader_failure_mode": "NONE",

  "trial_started_at": "2026-06-09T14:00:00Z",
  "trial_ended_at": "2026-06-09T14:00:42Z",
  "is_error": false,
  "stop_reason": "end_turn",

  "claude_error": null,
  "stream_log_path": "runs/20260609/swe-bench-fsspec__on__rep1/agent-logs/stream.jsonl",

  "atelier_bench_mode": "on",
  "atelier_root": "/tmp/atelier_bench_on_xyz123",
  "dataset_name": "terminal-bench-core",
  "dataset_version": "0.1.1"
}
```

**Field provenance:**
| Field | Source |
|-------|--------|
| `input_tokens`, `output_tokens`, `cache_*` | `result` line in `stream.jsonl` (`usage.*`) |
| `latency_ms` | `result` line `duration_ms` |
| `latency_api_ms` | `result` line `duration_api_ms` |
| `cost_usd` | `result` line `total_cost_usd` |
| `num_turns` | `result` line `num_turns` |
| `grader_verdict` | Derived from `TrialResults.is_resolved` → "pass"/"fail"/"error" |
| `grader_is_resolved` | `TrialResults.is_resolved` directly |
| `grader_failure_mode` | `TrialResults.failure_mode.value` |
| `trial_started_at`, `trial_ended_at` | `TrialResults.trial_started_at/ended_at` |
| `is_error`, `stop_reason` | `result` line |
| `atelier_bench_mode`, `atelier_root` | From `make_arm_env` call |

**File naming convention** (consistent with ARCHITECTURE.md):
```
<task_id>__<mode>__rep<N>.json
```
Written atomically via `os.replace()` to prevent partial files on kill.

---

## 5. Tasks YAML — 10 Pinned Code-Editing Tasks (TB-03)

[ASSUMED — selected by category/name analysis from `terminal-bench-core 0.1.1` task list; individual `solution.yaml` timeouts not inspected]

These 10 tasks from `terminal-bench-core 0.1.1` are code-editing focused and expected to complete in <30 min based on their nature:

```yaml
# benchmarks/terminalbench/tasks.yaml
# Pre-registered before first benchmark run (anti-p-hacking: Pitfall #6)
# Selection criteria: code-editing tasks from terminal-bench-core 0.1.1
# that do not require ML model downloads, kernel compilation, or VM startup.
# Selection date: 2026-06-09 (before first benchmark run)

dataset:
  name: terminal-bench-core
  version: "0.1.1"

tasks:
  - hello-world               # warmup: trivial print task, ~1 min
  - fix-pandas-version        # fix Python dependency compatibility, ~5 min
  - incompatible-python-fasttext  # fix Python version incompatibility, ~5 min
  - csv-to-parquet            # write data conversion script, ~5 min
  - fibonacci-server          # implement HTTP server returning Fibonacci, ~10 min
  - simple-web-scraper        # write web scraper script, ~10 min
  - fix-git                   # fix git configuration/state, ~5 min
  - swe-bench-fsspec          # SWE-bench style code fix (fsspec library), ~15 min
  - swe-bench-langcodes       # SWE-bench style code fix (langcodes library), ~15 min
  - grid-pattern-transform    # implement grid transformation algorithm, ~10 min
```

**Tasks explicitly excluded (>30 min or not code-editing):**
- `build-linux-kernel-qemu`, `build-initramfs-qemu` — kernel compilation, 60+ min
- `eval-mteb`, `cartpole-rl-training` — ML model training/eval, 30-60 min
- `hf-model-inference` — requires model download
- `reshard-c4-data` — large data processing
- `qemu-startup`, `qemu-alpine-ssh` — VM startup overhead
- `solana-data` — network-dependent blockchain data fetching

> **Note:** The `swe-bench-*` tasks may occasionally run 20-25 min depending on task complexity. If any exceed 30 min in practice, replace with `fix-permissions` or `organization-json-generator`. The tasks.yaml is pre-registered before the first run but CAN be adjusted with documented rationale before ANY run executes. [ASSUMED: individual task durations not verified; recommend quick-smoke with `--n-tasks 1 --quick` before full sweep]

---

## 6. Arm Isolation Implementation (TB-05)

[VERIFIED: Phase 1 bench/mode.py codebase inspection]

### Phase 1 deliverable: `atelier.bench.make_arm_env`
```python
def make_arm_env(atelier_root: Path, *, mode: BenchMode | None = None) -> dict[str, str]:
    """Returns {**os.environ, ATELIER_ROOT: str, ATELIER_BENCH_MODE: "on"|"off"}"""
```

The signature requires an explicit `atelier_root: Path` (an isolated temp dir). The `mode` kwarg accepts `BenchMode.ON` or `BenchMode.OFF`.

### Env var passing strategy for Docker containers

`AbstractInstalledAgent._env` controls what the Docker container sees. The mapping is:
1. **Host process** has `ATELIER_BENCH_MODE=on` (or `off`) and `ATELIER_ROOT=<tmp>`
2. **`_env` property** propagates `ATELIER_BENCH_MODE` to container via `env["ATELIER_BENCH_MODE"] = self._bench_mode`
3. `ANTHROPIC_API_KEY` must be explicitly passed (not inherited from Docker container env)
4. `ATELIER_ROOT` inside the container is **not the same as the host tmp dir** — Atelier's MCP server is not installed in the container. This env var in the container controls Claude Code's session behavior only. The key isolation happens at the host level (separate `ATELIER_ROOT` per arm).

### What makes on/off arms distinguishably different (TB-05)
| Feature | On arm | Off arm |
|---------|--------|---------|
| Model routing | Cross-vendor downtiering active | Passthrough (requested model used) |
| Context compaction | LLM-based compaction after N turns | Passthrough (no compaction) |
| Memory reads | Retrieves relevant past context | Returns `[]` (empty) |
| MCP tool visibility | Atelier tools visible in tool list | Atelier tools hidden |
| `ATELIER_BENCH_MODE` | `"on"` | `"off"` |
| `ATELIER_ROOT` | Fresh tmp dir (on-arm) | Fresh tmp dir (off-arm, different path) |

For TB-05, "distinguishably different transcripts" means:
- **Cost**: On-arm likely lower due to cache hits from compaction + routing optimization
- **Token counts**: `cache_read_input_tokens` higher in on-arm (compression cache)
- **Latency**: On-arm may have more turns (compaction calls) vs off-arm's straight completion
- The verifiable test: compare the two transcript JSONs; `atelier_bench_mode` field differs, and `cache_creation_input_tokens` in on-arm is typically non-zero.

### Additional env vars to pass through
```python
# In AtelierClaudeAgent._env — complete list:
env = {
    "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
    "ATELIER_BENCH_MODE": self._bench_mode,
    "FORCE_AUTO_BACKGROUND_TASKS": "1",
    "ENABLE_BACKGROUND_TASKS": "1",
}
# DO NOT pass through:
# ATELIER_DEV_MODE       — overrides bench mode visibility (PITFALLS #3b)
# ATELIER_NO_AUTO_UPDATE — set this on host before running harness
# CURSOR_WORKSPACE_ROOT  — host IDE artifact
# VSCODE_CWD             — host IDE artifact
```

Set `ATELIER_NO_AUTO_UPDATE=1` on the host before running the benchmark sweep to prevent auto-update from mutating code mid-run (PITFALLS #3d).

---

## 7. Codebase Patterns to Reuse

### From `benchmarks/mcp_tools/harness.py`
- `BenchCase`/`CaseResult` dataclass pattern — use same style for `AgentRunCase`/`Transcript`
- `_tokens()` using tiktoken — do NOT reuse for published counts; only for pre-flight estimates

### From `benchmarks/mcp_tools/_env.py`
- `configure_benchmark_runtime(root, workspace_root)` — do NOT call this in the TB runner (it mutates `os.environ` globally; use `make_arm_env` instead which returns a dict)

### From `benchmarks/swe/atelier_proxy.py`
- Pattern of subprocess invocation from Python (lines 1-30)
- Pattern of inserting `_repo_root` into `sys.path` to import `atelier.*` from the project root

### From `terminal_bench.agents.installed_agents.claude_code.claude_code_agent`
- `ALLOWED_TOOLS` list pattern
- `_env` property structure (only pass required keys)
- `_get_templated_script_path("setup.sh.j2")` for install script

### From `.planning/research/ARCHITECTURE.md`
- Atomic write: `os.replace(tmp_path, final_path)` for all transcript JSON files
- File-per-cell checkpoint pattern: presence of `<task>__<mode>__rep<N>.json` = completed
- Run output directory structure: `runs/<run-id>/raw/<task>__<mode>__rep<N>.json`

---

## Common Pitfalls

### Pitfall 1: `AbstractInstalledAgent.perform_task` always returns 0 tokens
**What goes wrong:** `TrialResults.total_input_tokens` and `total_output_tokens` are always 0 for `AbstractInstalledAgent` subclasses. The `perform_task` base implementation returns `AgentResult(total_input_tokens=0, total_output_tokens=0)` without attempting to parse the agent's output.
**Why it happens:** TerminalBench's installed-agent model runs the agent inside Docker via tmux; the framework doesn't try to parse agent-specific output formats.
**How to avoid:** Use the `tee /agent-logs/stream.jsonl` pattern and parse stream.jsonl from the host after the trial.
**Warning signs:** If all transcript JSONs show `input_tokens: 0`, the stream.jsonl file was not created or not found.

### Pitfall 2: Docker daemon required — CI must have it
**What goes wrong:** TerminalBench exits immediately if `docker.from_env()` fails. Every task requires a running Docker daemon.
**Why it happens:** TerminalBench is fundamentally a Docker harness.
**How to avoid:** Confirm `docker ps` returns exit 0 before running benchmark. Add a pre-flight check to runner.py.
**Warning signs:** `RuntimeError: Error while fetching server API version` from docker.from_env().

### Pitfall 3: ATELIER_DEV_MODE leaks into Docker
**What goes wrong:** `ATELIER_DEV_MODE=1` in host env → overrides `mcp_tool_visible_to_llm()` → Atelier tools visible even in off-arm.
**Why it happens:** `AbstractInstalledAgent._env` returns a dict that's set via shell export in the container. If `_env` inadvertently includes `ATELIER_DEV_MODE`, the off-arm is not clean.
**How to avoid:** Explicitly exclude `ATELIER_DEV_MODE` from `_env`. Never use `{**os.environ}` in `_env`.
**Warning signs:** Off-arm `TrialResults` shows more than the expected tool calls.

### Pitfall 4: Dataset download requires network on first run
**What goes wrong:** First `Harness.run()` call downloads the `terminal-bench-core 0.1.1` dataset from GitHub (~few hundred MB). Fails if GitHub is unreachable.
**Why it happens:** TerminalBench downloads and caches datasets from a registry.
**How to avoid:** Pre-download with `tb datasets download terminal-bench-core==0.1.1` before benchmark sweep. Or use `dataset_path=<local_path>` after manual download.
**Warning signs:** `requests.exceptions.ConnectionError` on first run.

### Pitfall 5: `tee` output interleaving in tmux
**What goes wrong:** tmux pane output may include control characters or color codes that corrupt the JSONL lines in stream.jsonl.
**Why it happens:** `2>&1 | tee` captures raw terminal output including escape codes.
**How to avoid:** Set `NO_COLOR=1` or `TERM=dumb` in `_env`. Parse stream.jsonl defensively: skip lines that fail `json.loads()`.
**Warning signs:** `json.JSONDecodeError` when parsing stream.jsonl.

### Pitfall 6: tasks.yaml modified after first run (p-hacking risk)
**What goes wrong:** Changing the task list after seeing preliminary results constitutes p-hacking.
**Why it happens:** Selection bias — picking tasks where on-arm wins best.
**How to avoid:** Commit `tasks.yaml` to git BEFORE the first benchmark run. The commit timestamp is the pre-registration proof. [VERIFIED: PITFALLS.md #6]
**Warning signs:** `git log --follow benchmarks/terminalbench/tasks.yaml` shows commits after benchmark run timestamps.

---

## Code Examples

### Complete AtelierClaudeAgent with setup.sh.j2 reference
```python
# benchmarks/terminalbench/agent_adapter.py
# Source: live inspection of terminal_bench 0.2.18 + STACK.md verified patterns
import json
import os
import shlex
from pathlib import Path
from terminal_bench.agents.installed_agents.abstract_installed_agent import AbstractInstalledAgent
from terminal_bench.terminal.models import TerminalCommand

CONTAINER_STREAM_LOG = "/agent-logs/stream.jsonl"

class AtelierClaudeAgent(AbstractInstalledAgent):
    def __init__(self, bench_mode: str = "on", model_name: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._bench_mode = bench_mode
        self._model_name = model_name

    @staticmethod
    def name() -> str:
        return "atelier-claude"

    @property
    def _env(self) -> dict[str, str]:
        env: dict[str, str] = {
            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            "ATELIER_BENCH_MODE": self._bench_mode,
            "FORCE_AUTO_BACKGROUND_TASKS": "1",
            "NO_COLOR": "1",        # prevent ANSI codes corrupting stream.jsonl
        }
        if self._model_name:
            env["ANTHROPIC_MODEL"] = self._model_name
        elif "ANTHROPIC_MODEL" in os.environ:
            env["ANTHROPIC_MODEL"] = os.environ["ANTHROPIC_MODEL"]
        # Explicitly NOT passing: ATELIER_DEV_MODE, ATELIER_NO_AUTO_UPDATE,
        # CURSOR_WORKSPACE_ROOT, VSCODE_CWD
        return env

    @property
    def _install_agent_script_path(self) -> Path:
        # Render install script from template (installs claude-code npm pkg)
        return self._get_templated_script_path("setup.sh.j2")

    def _run_agent_commands(self, instruction: str) -> list[TerminalCommand]:
        escaped = shlex.quote(instruction)
        allowed = "Bash Edit Write Read Glob Grep LS"
        cmd = (
            f"claude --verbose --output-format stream-json "
            f"-p {escaped} "
            f"--allowedTools {allowed} "
            f"--dangerously-skip-permissions "
            f"2>&1 | tee {CONTAINER_STREAM_LOG}"
        )
        return [TerminalCommand(
            command=cmd,
            min_timeout_sec=0.0,
            max_timeout_sec=float("inf"),
            block=True,
            append_enter=True,
        )]


def parse_stream_jsonl(log_path: Path) -> dict:
    """Extract token/cost/latency from the tee'd stream-json log."""
    result_line: dict | None = None
    model_name: str = ""

    for raw in log_path.read_text(errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "system" and obj.get("subtype") == "init":
            model_name = obj.get("model", "")
        if obj.get("type") == "result":
            result_line = obj

    if result_line is None:
        return {"error": "no_result_line", "model": model_name}

    u = result_line.get("usage", {})
    return {
        "model": model_name,
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": u.get("cache_read_input_tokens", 0),
        "cost_usd": result_line.get("total_cost_usd", 0.0),
        "latency_ms": result_line.get("duration_ms", 0),
        "latency_api_ms": result_line.get("duration_api_ms", 0),
        "num_turns": result_line.get("num_turns", 0),
        "is_error": result_line.get("is_error", False),
        "stop_reason": result_line.get("stop_reason", ""),
    }
```

### tasks.yaml loading
```python
# benchmarks/terminalbench/grader.py
import yaml
from pathlib import Path

def load_task_ids(tasks_yaml: Path = Path(__file__).parent / "tasks.yaml") -> list[str]:
    data = yaml.safe_load(tasks_yaml.read_text())
    return [t if isinstance(t, str) else str(t) for t in data["tasks"]]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual docker-py scripts for benchmark containers | `terminal-bench` Harness | terminal-bench 0.1.0 (2024) | TerminalBench handles all container lifecycle |
| `--output-format json` (full output) | `--output-format stream-json` with `--verbose` | claude-code ~2024 | stream-json gives per-event streaming + final result line with all fields |
| tiktoken for token counting | Anthropic API `usage` field | Always correct to use API; tiktoken was a stopgap | 10-30% accuracy improvement; required for publishable benchmarks |
| Single shared ATELIER_ROOT | Per-arm isolated tmp ATELIER_ROOT | Phase 1 | Eliminates cross-arm filesystem contamination |

**Deprecated/outdated:**
- `benchmarks/swe/../infra/runtime/benchmarking.py` `run_runtime_benchmark()`: Uses hardcoded fictional constants (`saved_per_lesson_in=350`). Never use for published benchmarks. [VERIFIED: PITFALLS.md #5]
- `tiktoken.get_encoding("cl100k_base")` for Claude token counts: 10-30% error vs actual billing. [VERIFIED: PITFALLS.md #4]

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | "Python 3.12 uv workspace" in TB-01 means a standalone uv project, not a uv workspace member | §3 Workspace Setup | If it means a true workspace member, root pyproject.toml needs `[tool.uv.workspace]` added; medium effort to change |
| A2 | 10 selected tasks complete in <30 min based on name/category analysis (no solution.yaml timeout inspection) | §5 Tasks YAML | If any task regularly exceeds 30 min (e.g., swe-bench tasks), they should be replaced with `fix-permissions` or `organization-json-generator`; low risk |
| A3 | `tee /agent-logs/stream.jsonl` inside tmux session writes reliably to the host-mounted volume path | §1 Integration / §6 Arm Isolation | If tmux buffering or Docker volume latency causes incomplete writes, post-processing will miss the result line; fallback is `session.capture_pane()` approach |
| A4 | `AtelierClaudeAgent` can use `_get_templated_script_path("setup.sh.j2")` with a custom template in `benchmarks/terminalbench/` | §1 Code Examples | If the template discovery uses `inspect.getfile(self.__class__)` (which it does), the setup.sh.j2 must be in the same directory as agent_adapter.py — this is correct and works |
| A5 | TerminalBench agent logs path on host is `<output_path>/**/<trial_name>/agent-logs/stream.jsonl` (found via `Path.rglob("stream.jsonl")`) | §4 Transcript Schema | If the path structure is different (e.g., task_id not in path), `rglob("stream.jsonl")` still works; low risk |

---

## Open Questions

1. **Task duration verification**
   - What we know: task names suggest short duration; `max_agent_timeout_sec` in solution.yaml determines TB's hard cutoff
   - What's unclear: actual observed p50 run times for the 10 selected tasks
   - Recommendation: Run `tb run --dataset terminal-bench-core==0.1.1 --task-id hello-world --agent claude-code --no-rebuild` as a smoke test before the full sweep

2. **ClaudeCode setup.sh.j2 template location**
   - What we know: `ClaudeCodeAgent._get_templated_script_path("claude-code-setup.sh.j2")` uses a specific template filename
   - What's unclear: Should we reuse `ClaudeCodeAgent`'s template, copy it, or write our own?
   - Recommendation: Copy the template from `terminal_bench.agents.installed_agents.claude_code/claude-code-setup.sh.j2` into `benchmarks/terminalbench/setup.sh.j2`; this avoids depending on internal TB paths

3. **Agent import path in Harness constructor**
   - What we know: `Harness(agent_import_path="benchmarks.terminalbench.agent_adapter.AtelierClaudeAgent")` requires the module to be importable
   - What's unclear: Whether `uv run --project benchmarks/` makes `benchmarks.terminalbench.*` importable or if Python path manipulation is needed
   - Recommendation: Use `agent_name=None` with a pre-instantiated agent object passed differently; or add `benchmarks/` to `PYTHONPATH`

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker daemon | TerminalBench (all tasks) | ✓ | 29.1.3 | None — TerminalBench is fundamentally Docker-based |
| Python 3.12 | benchmarks/ workspace | ✓ | 3.12.10 (uv managed) | Python 3.13.7 also satisfies `>=3.12` |
| `claude` CLI | TB-02 subprocess invocation | ✓ (`@anthropic-ai/claude-code` v2.1.153 in PATH) | 2.1.153 | None — must be installed in Docker container by setup.sh |
| `ANTHROPIC_API_KEY` | `claude -p` authentication | ✓ (assumed in env) | — | None — benchmark fails without it |
| `terminal-bench` (Python 3.12 venv) | Harness API | ✗ (only installed at Python 3.13) | Needs install | `uv add terminal-bench==0.2.18` in benchmarks/ venv |
| `uv` | benchmarks/ project management | ✓ | 0.11.7 | — |
| GitHub access | Dataset download (first run) | ✓ (assumed — other gh commands succeed) | — | `--dataset-path` with pre-downloaded dataset |

**Missing dependencies with no fallback:**
- Docker daemon — confirmed available but must be running during benchmark execution
- `ANTHROPIC_API_KEY` — must be set in environment

**Missing dependencies with fallback:**
- `terminal-bench` in Python 3.12 venv — install step required; available on PyPI

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ (from root dev dependencies) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` at root |
| Quick run command | `pytest tests/benchmarks/terminalbench/ -x -m "not slow"` |
| Full suite command | `pytest tests/benchmarks/terminalbench/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TB-01 | benchmarks/pyproject.toml installs with Python 3.12 | smoke | `cd benchmarks && uv run python -c "import terminal_bench"` | ❌ Wave 0 |
| TB-02 | `parse_stream_jsonl` extracts all fields from fixture | unit | `pytest tests/benchmarks/terminalbench/test_agent_adapter.py::test_parse_stream_jsonl -x` | ❌ Wave 0 |
| TB-02 | `AtelierClaudeAgent._run_agent_commands` produces correct command string | unit | `pytest tests/benchmarks/terminalbench/test_agent_adapter.py::test_run_agent_commands -x` | ❌ Wave 0 |
| TB-03 | tasks.yaml has exactly 10 task IDs | unit | `pytest tests/benchmarks/terminalbench/test_tasks_yaml.py::test_task_count -x` | ❌ Wave 0 |
| TB-04 | Transcript JSON contains all required fields | unit | `pytest tests/benchmarks/terminalbench/test_transcript_schema.py -x` | ❌ Wave 0 |
| TB-05 | On/off arms produce different `atelier_bench_mode` field | unit | `pytest tests/benchmarks/terminalbench/test_agent_adapter.py::test_arm_env_differs -x` | ❌ Wave 0 |

### Wave 0 Gaps
- [ ] `tests/benchmarks/terminalbench/__init__.py` — test package init
- [ ] `tests/benchmarks/terminalbench/test_agent_adapter.py` — covers TB-02, TB-05 with mocked Harness
- [ ] `tests/benchmarks/terminalbench/test_tasks_yaml.py` — covers TB-03
- [ ] `tests/benchmarks/terminalbench/test_transcript_schema.py` — covers TB-04
- [ ] `tests/benchmarks/terminalbench/fixtures/sample_stream.jsonl` — fixture for parse_stream_jsonl tests

> Note: TB-01 (workspace install) is a smoke test run via `uv run`, not pytest. TB-02/04/05 unit tests mock the TerminalBench Harness — no Docker required for the unit test suite.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Benchmark runner, no user auth |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | Dev-only tool |
| V5 Input Validation | Partial | `shlex.quote(instruction)` before subprocess injection |
| V6 Cryptography | No | |
| Subprocess injection | Yes | `shlex.quote` on task instruction before embedding in shell command |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Task instruction shell injection | Tampering | `shlex.quote(instruction)` in `_run_agent_commands` — already in ClaudeCode pattern |
| API key exposure in logs | Info disclosure | `_env` does NOT log; `_create_env_setup_file` writes to container-internal file, not stdout |
| Partial transcript on kill | Integrity | `os.replace(tmp, final)` atomic write pattern from ARCHITECTURE.md |

---

## Sources

### Primary (HIGH confidence)
- `terminal_bench` package at `/home/pankaj/.local/lib/python3.13/site-packages/terminal_bench/` — direct source inspection of `harness.py`, `models.py`, `base_agent.py`, `abstract_installed_agent.py`, `claude_code_agent.py`, `dataset.py`, `registry/client.py`
- `.planning/research/STACK.md` — live `claude -p` run capturing exact result line JSON (2026-05-28)
- `.planning/research/PITFALLS.md` — codebase-verified contamination risks
- `.planning/research/ARCHITECTURE.md` — agent_adapter pattern, transcript schema, atomic write pattern
- `src/atelier/bench/mode.py` — Phase 1 delivered code; `make_arm_env` signature verified
- `registry.json` — live fetch from `https://raw.githubusercontent.com/laude-institute/terminal-bench/main/registry.json` for task ID list
- `uv python list` — Python version availability confirmed

### Secondary (MEDIUM confidence)
- `tb datasets list` — confirmed dataset names and versions
- `tb run --help` — confirmed CLI options and dataset loading pattern
- `tb tasks --help` — confirmed no task listing command (tasks discovered via registry API)

### Tertiary (LOW confidence — see Assumptions Log)
- Task duration estimates: based on task name/category, not measured run times

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — package installed and inspected live
- Architecture: HIGH — verified against actual AbstractInstalledAgent source code
- Task selection: MEDIUM — task IDs from registry are verified; durations are ASSUMED
- Workspace setup: HIGH — uv 0.11.7 and Python 3.12.10 confirmed available

**Research date:** 2026-06-09
**Valid until:** 2026-09-09 (terminal-bench has fast release cadence; re-verify if using versions other than 0.2.18)
