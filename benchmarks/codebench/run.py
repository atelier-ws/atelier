"""Head-to-head runner: vanilla Claude Code (baseline) vs Atelier-enabled (candidate).

For each task and arm we:
  1. prepare an isolated workspace (empty / git checkout / bundled copy),
  2. start mitmdump capturing the model traffic to a .flow file,
  3. run ``claude -p <prompt>`` headless, pinned to one model, through the proxy,
  4. record cost (real, from CLI JSON), latency, and token usage.

Baseline uses an isolated CLAUDE_CONFIG_DIR with plugins/hooks/MCP stripped
(but real subscription credentials copied in) so it is contamination-free.
The Atelier arm adds the atelier stdio MCP server + a tool-discipline CLAUDE.md.

Usage:
    uv run python -m benchmarks.codebench.run task1 --model sonnet

    # Cloud providers - reads credentials from .env or current env automatically:
    uv run python -m benchmarks.codebench.run task1 -a atelier \
        --provider aws --model us.anthropic.claude-sonnet-4-5-20250929-v1:0
    uv run python -m benchmarks.codebench.run task1 -a atelier \
        --provider gcp --model claude-sonnet-4-5@20250929
    uv run python -m benchmarks.codebench.run task1 -a atelier \
        --provider azure --model claude-sonnet-4-5
    uv run python -m benchmarks.codebench.run task1 -a baseline atelier \
        --provider openrouter --model anthropic/claude-sonnet-4-5

    # Manual override (--agent-env takes precedence over --provider):
    uv run python -m benchmarks.codebench.run task1 -a baseline atelier \
        --model claude-opus-4-8 \
        --agent-env ANTHROPIC_BASE_URL=https://openrouter.ai/api \
        --agent-env-from-host ANTHROPIC_AUTH_TOKEN=OPENROUTER_API_KEY \
        --agent-env ANTHROPIC_API_KEY=
    uv run python -m benchmarks.codebench.run --report results/<run_dir>

    # Owned-agent arm (Atelier runs the loop itself on YOUR API key; different
    # price/savings profile than the host-plugin "atelier" arm). Requires a real
    # provider key, e.g. ANTHROPIC_API_KEY, and an explicit --model:
    uv run python -m benchmarks.codebench.run task1 \
    """

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from atelier.core.capabilities.host_runners import (
    CLAUDE_PROVIDER_PRESETS,
    build_driver_command,
)
from atelier.core.capabilities.pricing import usage_cost_breakdown_usd, usage_cost_usd

from benchmarks.codebench.tasks import BY_ID, TASKS, Task
from benchmarks.wire_savings.report import aggregate, flow_records

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "benchmarks" / "codebench" / "results"
CA_CERT = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"

EMPTY_MCP: dict[str, dict[str, object]] = {"mcpServers": {}}
VALID_ARMS = ("baseline", "atelier")
PERSISTENT_WORKSPACE_ROOT = Path(
    os.environ.get("CODEBENCH_WORKSPACE_ROOT", str(Path(tempfile.gettempdir()) / "codebench_workspaces"))
)
PROVIDER_ALIASES: dict[str, str] = {
    "aws": "aws-claude",
    "bedrock": "aws-claude",
    "gcp": "gcp-claude",
    "vertex": "gcp-claude",
    "azure": "azure-claude",
    "openrouter": "openrouter-claude",
}
CLI_DRIVERS = ("claude", "atelier-run")
# Arms that drive many model + tool round-trips and so dominate wall time.
HEAVY_ARMS = ("atelier",)
# Heuristic floor: on a non-trivial task a tool-heavy arm routinely issues this
# many model round-trips. If --rate-limit-rpm x --timeout cannot fit this many
# requests, the heavy arm will very likely hit the timeout, so we warn up front.
# Calibrated above the ~300-request budget of rpm=10 x 1800s, which was observed
# to time out in practice.
RPM_TIMEOUT_MIN_REQUESTS = 400
PLACEHOLDER_RESPONSE_MARKERS = (
    "i'm ready to help",
    "what would you like to work on",
    "how can i help",
    "what can i help you with",
)
META_ACTION_MARKERS = (
    "i need to research",
    "let me research",
    "i'll start by",
    "i will start by",
    "let me investigate",
    "search the web",
    "search broadly",
    "let me search",
)
CLARIFICATION_REQUEST_MARKERS = (
    "could you tell me more",
    "could you clarify",
    "please provide",
    "need more context",
    "is there a repo",
    "should i scaffold",
    "once you share",
    "share the source",
    "actual task description",
)
WORKSPACE_CONFUSION_MARKERS = (
    "workspace contains only",
    "workspace only contains",
    "only the `claude.md` file",
    "only the claude.md file",
    "empty project directory",
    "no git repository",
)
RUNTIME_ERROR_MARKERS = (
    "requires more credits",
    "the server returned http",
    "api error:",
    "permission denied",
    "timed out",
)


# Sentinel reason set when a trial never produced gradeable content (subprocess
# crash or timeout). Distinct from off-topic / placeholder *content* invalidity.
EXECUTION_FAILED_REASON = "trial execution failed (ok=False)"
STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "cache",
        "could",
        "each",
        "from",
        "have",
        "into",
        "last",
        "make",
        "must",
        "name",
        "prompt",
        "return",
        "should",
        "task",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "those",
        "through",
        "using",
        "with",
        "without",
        "work",
        "would",
        "your",
    }
)
ATELIER_CLAUDE_PLUGIN_ROOT = REPO_ROOT / "integrations" / "claude" / "plugin"


def _atelier_claude_agent_args() -> list[str]:
    return [
        "--plugin-dir",
        str(ATELIER_CLAUDE_PLUGIN_ROOT),
        "--agent",
        "atelier:code",
    ]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return int(port)


def _wait_port(port: int, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with (
            contextlib.suppress(OSError),
            socket.create_connection(("127.0.0.1", port), timeout=0.5),
        ):
            return True
        time.sleep(0.2)
    return False


def _make_baseline_config(dest: Path | None = None) -> Path:
    """Isolated CLAUDE_CONFIG_DIR: real auth, no plugins/hooks/MCP.

    Idempotent when *dest* is given: an already-populated config dir is reused
    so ``--resume`` can still find the prior session transcript.
    """
    cfg = dest or Path(_mktemp("cfg-"))
    cfg.mkdir(parents=True, exist_ok=True)
    if (cfg / ".claude.json").exists():
        return cfg
    src = Path.home() / ".claude.json"
    data = json.loads(src.read_text())
    for k in ("enabledPlugins", "hooks", "mcpServers"):
        data.pop(k, None)
    for proj in data.get("projects", {}).values():
        if isinstance(proj, dict):
            for k in ("mcpServers", "enabledPlugins", "hooks"):
                proj.pop(k, None)
    (cfg / ".claude.json").write_text(json.dumps(data))
    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.exists():
        shutil.copy(creds, cfg / ".credentials.json")
    return cfg


def _mktemp(prefix: str) -> str:
    import tempfile

    return tempfile.mkdtemp(prefix=f"codebench-{prefix}")


def prepare_workspace(task: Task, workspace: Path | None = None) -> Path:
    ws = workspace or Path(_mktemp(f"ws-{task.id}-"))
    if ws.exists() and any(ws.iterdir()):
        return ws
    ws.mkdir(parents=True, exist_ok=True)
    kind = task.source[0]
    if kind == "empty":
        pass
    elif kind == "workspace":
        src = task.workspace_src()
        if not src or not src.exists():
            raise FileNotFoundError(f"bundled workspace missing for {task.id}: {src}")
        for item in src.iterdir():
            dst = ws / item.name
            if item.is_dir():
                shutil.copytree(item, dst)
            else:
                shutil.copy(item, dst)
    elif kind == "repo":
        if len(task.source) < 3:
            raise ValueError(f"repo source missing url/commit for {task.id}: {task.source}")
        url, commit = task.source[1], task.source[2]
        subprocess.run(["git", "clone", "--quiet", url, str(ws)], check=True, timeout=900)
        if commit:
            subprocess.run(["git", "-C", str(ws), "checkout", "--quiet", commit], check=True, timeout=120)
    else:
        raise ValueError(f"unknown source kind {kind}")

    # Run per-task setup commands after the workspace is populated.
    for cmd in task.setup_cmds:
        print(f"  [setup:{task.id}] {cmd}", flush=True)
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(ws),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                print(
                    f"  [setup:{task.id}] WARNING: '{cmd}' exited {result.returncode}: "
                    f"{(result.stderr or result.stdout or '').strip()[:200]}",
                    flush=True,
                )
        except subprocess.TimeoutExpired:
            print(f"  [setup:{task.id}] WARNING: '{cmd}' timed out after 300s", flush=True)

    return ws


_LANGUAGE_PREREQS: dict[str, list[tuple[str, str]]] = {
    # language → list of (binary, install_hint) pairs
    "swift": [("swift", "Install Swift from https://swift.org/download")],
    "rust": [("cargo", "Install Rust from https://rustup.rs")],
    "typescript": [
        ("node", "Install Node.js from https://nodejs.org"),
        ("npm", "Install Node.js from https://nodejs.org"),
    ],
    "python": [("uv", "Install uv: curl -Ls https://astral.sh/uv/install.sh | sh")],
}


def check_prereqs(tasks: list[Task]) -> bool:
    """Verify required binaries are available for the selected tasks.

    Prints a summary and returns True if all prerequisites are satisfied.
    Returns False if any required binary is missing (does not raise).
    """
    required: dict[str, str] = {}  # binary → install_hint
    languages = {t.language for t in tasks}
    for lang in languages:
        for binary, hint in _LANGUAGE_PREREQS.get(lang, []):
            required[binary] = hint

    missing = []
    for binary, hint in required.items():
        if not shutil.which(binary):
            missing.append((binary, hint))

    if missing:
        print("\n⚠  Missing prerequisites:", flush=True)
        for binary, hint in missing:
            print(f"   • {binary}: {hint}", flush=True)
        print("", flush=True)
        return False

    print(
        f"✓ Prerequisites satisfied: {', '.join(sorted(required))}",
        flush=True,
    )
    return True


@dataclass
class ArmResult:
    task: str
    arm: str
    rep: int
    ok: bool
    cost_usd: float
    duration_ms: int
    duration_api_ms: int
    num_turns: int
    input_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    output_tokens: int
    models: list[str]
    is_error: bool
    result_excerpt: str
    flow_path: str
    valid: bool = True
    validity_reason: str = ""
    correct: bool | None = None
    score: float | None = None
    judge_model: str = ""
    judge_reason: str = ""
    saved_usd: float = 0.0
    saved_tokens: int = 0
    thinking_tokens: int = 0
    model_usage: dict[str, dict[str, int]] = field(default_factory=dict)
    timed_out: bool = False
    workspace: str = ""


def _result_total_tokens(result: ArmResult) -> int:
    """Total billed tokens for one run (same basis the cost is charged on)."""
    return result.input_tokens + result.cache_read_tokens + result.cache_creation_tokens + result.output_tokens


def _apply_savings(results: list[ArmResult]) -> None:
    """Backfill real cross-arm savings in place.

    Each non-baseline run is compared against the baseline run of the *same task
    and rep*: ``saved_usd``/``saved_tokens`` is how much less (positive) or more
    (negative) it spent than that baseline. Baseline rows are the reference and
    stay zero; runs with no matching baseline also stay zero (savings undefined).
    """
    baseline_by_key = {(r.task, r.rep): r for r in results if r.arm == "baseline"}
    for r in results:
        base = None if r.arm == "baseline" else baseline_by_key.get((r.task, r.rep))
        if base is None:
            r.saved_usd = 0.0
            r.saved_tokens = 0
        else:
            r.saved_usd = round(base.cost_usd - r.cost_usd, 4)
            r.saved_tokens = _result_total_tokens(base) - _result_total_tokens(r)


def _task_verify(task: Task) -> tuple[str | None, str]:
    """Read the objective grading command + mode from the task's config.yaml.

    Returns ``(command, mode)``. ``mode`` is ``"binary"`` (the gate IS the grade)
    or ``"floor"`` (the gate must pass, then the LLM judge scores conformance).
    Returns ``(None, "binary")`` when the task defines no verify block.
    """
    config_path = task.prompt_path().parent / "config.yaml"
    if not config_path.exists():
        return None, "binary"
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None, "binary"
    verify = data.get("verify") if isinstance(data, dict) else None
    if isinstance(verify, dict) and verify.get("command"):
        mode = "floor" if verify.get("mode") == "floor" else "binary"
        return str(verify["command"]), mode
    return None, "binary"


def _run_verify(task: Task, command: str, workspace: str) -> tuple[bool, str]:
    """Run a task's verify command in its workspace; pass == exit code 0."""
    ws = Path(workspace)
    env = dict(os.environ)
    venv = ws / ".venv"
    if task.language == "python" and venv.is_dir():
        env["VIRTUAL_ENV"] = str(venv)
        env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False, "verify command timed out (600s)"
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    tail = lines[-1][:200] if lines else ""
    return proc.returncode == 0, f"verify exit={proc.returncode}: {tail}"


def _apply_verify(results: list[ArmResult]) -> None:
    """Objectively grade results whose task defines a `verify` command.

    Runs the command in the produced workspace and sets correct/score from the
    exit code (1.0 pass / 0.0 fail), marking ``judge_model='verify'`` so the LLM
    judge skips the row. Tasks with no verify command -- or whose workspace is
    no longer on disk -- are left untouched for the judge.
    """
    for r in results:
        task = BY_ID.get(r.task)
        if task is None or not r.ok or not r.workspace:
            continue
        if not Path(r.workspace).is_dir():
            continue
        command, mode = _task_verify(task)
        if not command:
            continue
        ok, detail = _run_verify(task, command, r.workspace)
        if ok:
            # Ground truth: a passing gate proves the run genuinely did the task,
            # so override any soft keyword-overlap validity false-negative.
            r.valid = True
            r.validity_reason = ""
        if mode == "floor" and ok:
            # Floor passed: leave correct/score for the LLM judge to score conformance.
            r.judge_reason = f"floor passed ({detail})"[:300]
            continue
        r.correct = ok
        r.score = 1.0 if ok else 0.0
        r.judge_model = "verify"
        r.judge_reason = (detail if mode == "binary" else f"floor failed ({detail})")[:300]


def _fmt_hms(seconds: float) -> str:
    """Format a duration as a compact h/m/s string for progress lines."""
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _recover_flow_result(
    flow_path: Path,
    task: str,
    arm: str,
    rep: int,
    model: str,
    wall_duration_ms: int,
    excerpt: str,
    *,
    timed_out: bool,
) -> ArmResult:
    """Best-effort ArmResult rebuilt from captured proxy traffic.

    When the CLI is killed before it prints its JSON receipt (e.g. the run hits
    --timeout), the .flow file still holds every completed model round-trip. We
    recover the real token usage and cost from it so the trial is recorded with
    its true price instead of $0.
    """
    input_tokens = output_tokens = cache_read = cache_write = requests = 0
    cost_usd = 0.0
    if flow_path.exists():
        with contextlib.suppress(Exception):
            stats = aggregate("flow", flow_records(str(flow_path)))
            usage = stats.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cache_read = usage.cache_read_input_tokens
            cache_write = usage.cache_creation_input_tokens
            requests = stats.requests
    if model and (input_tokens or output_tokens or cache_read or cache_write):
        with contextlib.suppress(Exception):
            cost_usd = usage_cost_usd(
                model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            )
    detail = f"{excerpt} (recovered ${cost_usd:.4f} / {requests} request(s) from flow)"
    return ArmResult(
        task=task,
        arm=arm,
        rep=rep,
        ok=False,
        cost_usd=cost_usd,
        duration_ms=wall_duration_ms,
        duration_api_ms=wall_duration_ms,
        num_turns=requests,
        input_tokens=input_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_write,
        output_tokens=output_tokens,
        models=[model] if model else [],
        is_error=True,
        result_excerpt=detail[:4000],
        flow_path=str(flow_path),
        timed_out=timed_out,
    )


def _parse_claude_result(stdout: str, flow_path: Path, task: str, arm: str, rep: int) -> ArmResult:
    try:
        d = json.loads(stdout)
    except json.JSONDecodeError:
        return ArmResult(task, arm, rep, False, 0.0, 0, 0, 0, 0, 0, 0, 0, [], True, stdout[:200], str(flow_path))

    u = d.get("usage", {}) or {}
    model_usage = d.get("modelUsage", {}) or {}
    cost_usd = float(d.get("total_cost_usd", 0.0) or 0.0)
    if cost_usd <= 0.0 and u:
        # Bedrock/Vertex and some gateways report total_cost_usd=0; recompute
        # from token usage via the shared pricing catalog so savings math works.
        model_id = next(iter(model_usage), "") or ""
        if model_id:
            with contextlib.suppress(Exception):
                cost_usd = usage_cost_usd(
                    model_id,
                    input_tokens=int(u.get("input_tokens", 0) or 0),
                    output_tokens=int(u.get("output_tokens", 0) or 0),
                    cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
                    cache_write_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
                )
    return ArmResult(
        task=task,
        arm=arm,
        rep=rep,
        ok=not d.get("is_error", False),
        cost_usd=cost_usd,
        duration_ms=int(d.get("duration_ms", 0) or 0),
        duration_api_ms=int(d.get("duration_api_ms", 0) or 0),
        num_turns=int(d.get("num_turns", 0) or 0),
        input_tokens=int(u.get("input_tokens", 0) or 0),
        cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        thinking_tokens=int(u.get("thinking_tokens", 0) or 0),
        model_usage=model_usage,
        models=list(model_usage.keys()),
        is_error=bool(d.get("is_error", False)),
        result_excerpt=str(d.get("result", ""))[:4000],
        flow_path=str(flow_path),
    )


def _iter_jsonl_objects(text: str) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def _flatten_text_blocks(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            for key in ("text", "content", "value", "message"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    parts.append(raw)
                    break
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "value", "message"):
            raw = value.get(key)
            flattened = _flatten_text_blocks(raw)
            if flattened:
                return flattened
    return ""


def _usage_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(float(value))
    return 0


def _parse_atelier_run_result(
    stdout: str,
    flow_path: Path,
    task: str,
    arm: str,
    rep: int,
    wall_duration_ms: int,
) -> ArmResult:
    """Parse the `atelier run start` headless owned-agent receipt from stdout.

    `atelier run report` rebuilds an empty receipt, so the only populated token/
    cost figures live in the `format_receipt()` block printed by `run start`.
    """
    text = stdout or ""
    session_match = re.search(r"session=(\S+)", text) or re.search(r"^Session:\s*(\S+)", text, re.MULTILINE)
    session_id = session_match.group(1) if session_match else ""
    model_match = re.search(r"model=(\S+)", text) or re.search(r"Provider:\s*\S+\s*/\s*(\S+)", text)
    model = model_match.group(1) if model_match else ""

    def _money(label: str) -> float:
        m = re.search(rf"^{label}:\s*\$([0-9.]+)", text, re.MULTILINE)
        return float(m.group(1)) if m else 0.0

    cost_usd = _money("Cost")
    input_tokens = cache_read = cache_write = output_tokens = 0
    phase_lines = 0
    for m in re.finditer(
        r"input=\s*([\d,]+)\s+cache_read=\s*([\d,]+)" r"\s+cache_write=\s*([\d,]+)\s+output=\s*([\d,]+)",
        text,
    ):
        phase_lines += 1
        input_tokens += int(m.group(1).replace(",", ""))
        cache_read += int(m.group(2).replace(",", ""))
        cache_write += int(m.group(3).replace(",", ""))
        output_tokens += int(m.group(4).replace(",", ""))
    ok = bool(session_id) and "Session saved:" in text
    turns_match = re.search(r"^Turns:\s*([\d,]+)", text, re.MULTILINE)
    turn_count = int(turns_match.group(1).replace(",", "")) if turns_match else phase_lines
    return ArmResult(
        task=task,
        arm=arm,
        rep=rep,
        ok=ok,
        cost_usd=cost_usd,
        duration_ms=wall_duration_ms,
        duration_api_ms=wall_duration_ms,
        num_turns=turn_count,
        input_tokens=input_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_write,
        output_tokens=output_tokens,
        models=[model] if model else [],
        is_error=not ok,
        result_excerpt=text.strip()[-4000:],
        flow_path=str(flow_path),
    )


def _parse_cli_result(
    stdout: str,
    flow_path: Path,
    task: str,
    arm: str,
    rep: int,
    cli_driver: str,
    wall_duration_ms: int,
) -> ArmResult:
    if cli_driver == "claude":
        result = _parse_claude_result(stdout, flow_path, task, arm, rep)
        if result.duration_ms == 0:
            result.duration_ms = wall_duration_ms
        if result.duration_api_ms == 0:
            result.duration_api_ms = wall_duration_ms
        return result
    if cli_driver == "atelier-run":
        return _parse_atelier_run_result(stdout, flow_path, task, arm, rep, wall_duration_ms)
    raise ValueError(f"unsupported cli driver: {cli_driver}")


def _extract_keywords(text: str, *, limit: int = 24) -> set[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{3,}", text.lower())
    counts: dict[str, int] = {}
    for token in tokens:
        if token in STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return {token for token, _count in ranked[:limit]}


def _extract_identifiers(text: str) -> set[str]:
    """Code identifiers (CamelCase, snake_case, `backticked` symbols) from text.

    A response that names the task's real symbols or filenames is engaging with
    it even when prose-word overlap is low -- a stronger on-topic signal than
    plain words, which the keyword heuristic alone misses on terse summaries.
    """
    ids: set[str] = set()
    for span in re.findall(r"`([^`]+)`", text):
        ids.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", span))
    ids.update(re.findall(r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]+\b", text))  # CamelCase
    ids.update(re.findall(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b", text))  # snake_case
    return {i.lower() for i in ids if i.lower() not in STOPWORDS}


def _validate_result_excerpt(task: Task, excerpt: str) -> tuple[bool, str, bool]:
    """Return ``(valid, reason, hard)``.

    ``hard`` marks failures certain enough to flip ``ok`` (empty / error /
    placeholder output). Soft failures — the keyword-overlap heuristics — are
    advisory only: they set ``valid=False`` for reporting but MUST NOT fail an
    otherwise-successful run, because terse-by-design output (e.g. the atelier
    arm's "do not print a summary banner") legitimately has low prompt overlap
    and was being scored as a failure, biasing the comparison against atelier.
    """
    text = excerpt.strip()
    lowered = text.lower()
    if not text:
        return False, "empty response", True
    if lowered.startswith("harness error:"):
        return False, "harness/runtime error", True
    if any(marker in lowered for marker in RUNTIME_ERROR_MARKERS):
        return False, "runtime/provider error surfaced in result", True
    # "error:" only counts when line-anchored (real CLI/runtime errors), so prose
    # like "...produces an immediate error:" in a legitimate summary never trips it.
    if re.search(r"(?m)^\s*error:", lowered):
        return False, "runtime/provider error surfaced in result", True
    if any(marker in lowered for marker in PLACEHOLDER_RESPONSE_MARKERS):
        return False, "generic placeholder response", True
    if text.lstrip().startswith('{"title"'):
        return False, "session-title payload instead of task response", True
    task_text = f"{task.prompt()}\n{_task_description(task)}"
    task_keywords = _extract_keywords(task_text)
    # Match task keywords against ALL response tokens, not the response's own
    # top-N frequency ranking: long structured summaries (tables, test rosters)
    # rank repeated table words above task terms and false-positive as off-topic.
    response_keywords = {
        token for token in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{3,}", lowered) if token not in STOPWORDS
    }
    # Fold in code identifiers (symbols/filenames) the response names: a stronger
    # on-topic signal than prose words, so a terse summary that cites the right
    # symbols is not flagged off-topic for low word overlap.
    overlap = (task_keywords & response_keywords) | (_extract_identifiers(task_text) & response_keywords)
    list_item_count = sum(
        1 for line in text.splitlines() if line.lstrip().startswith("- ") or re.match(r"^\s*\d+\.\s", line) is not None
    )
    if len(overlap) == 0 and list_item_count >= 3:
        return False, f"off-task capability/list response (list_items={list_item_count})", False
    if any(marker in lowered for marker in META_ACTION_MARKERS) and len(overlap) < 2:
        return (
            False,
            f"off-topic planning/research response (keyword overlap={len(overlap)})",
            False,
        )
    if (
        any(marker in lowered for marker in CLARIFICATION_REQUEST_MARKERS)
        and len(task.prompt()) > 200
        and len(overlap) < 2
    ):
        return False, f"unnecessary clarification request (keyword overlap={len(overlap)})", False
    if any(marker in lowered for marker in WORKSPACE_CONFUSION_MARKERS) and len(overlap) < 2:
        return (
            False,
            f"workspace confusion overrode task prompt (keyword overlap={len(overlap)})",
            False,
        )
    if task_keywords and len(overlap) == 0:
        return False, "no task keyword overlap", False
    return True, "", False


def _apply_result_validity(task: Task, result: ArmResult) -> ArmResult:
    # If the trial already failed execution (ok=False), propagate that as invalid
    # to avoid false positives in validity reporting.
    if not result.ok:
        result.valid = False
        result.validity_reason = result.validity_reason or EXECUTION_FAILED_REASON
        return result

    valid, reason, hard = _validate_result_excerpt(task, result.result_excerpt)
    result.valid = valid
    result.validity_reason = reason
    # Only a hard failure flips ok; soft keyword-overlap heuristics stay advisory
    # so terse correct runs (esp. the atelier arm) are not failed for low overlap.
    if not valid and hard:
        result.ok = False
    return result


def _is_content_invalid(result: ArmResult) -> bool:
    """True only when a run completed but produced off-topic / placeholder /
    empty *content* -- the case that makes a cost/token comparison meaningless.

    Timeouts and transport/execution failures are recorded benchmark outcomes
    (surfaced on the ``Timeouts`` / ``Runs ok`` lines and via exit code 1), not
    content contamination, so they are excluded here: a lone timeout must not
    trip the "comparisons are not meaningful" alarm or the exit-2 path.
    """
    if result.valid or result.timed_out:
        return False
    return result.validity_reason != EXECUTION_FAILED_REASON


def _parse_agent_env(entries: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for entry in entries or []:
        key, sep, value = entry.partition("=")
        if not sep or not key:
            raise ValueError(f"invalid --agent-env entry: {entry!r}; expected KEY=VALUE")
        parsed[key] = value
    return parsed


def _env_file_candidates() -> tuple[Path, ...]:
    return (
        REPO_ROOT / ".env",
        REPO_ROOT / "benchmarks" / ".env",
        REPO_ROOT / "benchmarks" / "codebench" / ".env",
    )


def _parse_env_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].strip()
    key, sep, value = stripped.partition("=")
    if not sep or not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key.strip(), value


def _resolve_host_env_value(name: str) -> str | None:
    if name in os.environ:
        return os.environ[name]
    for path in _env_file_candidates():
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_assignment(line)
            if parsed is None:
                continue
            key, value = parsed
            if key == name:
                return value
    return None


def _parse_agent_env_from_host(entries: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for entry in entries or []:
        dest, sep, source = entry.partition("=")
        if not sep or not dest or not source:
            raise ValueError(f"invalid --agent-env-from-host entry: {entry!r}; expected DEST_KEY=SOURCE_ENV")
        value = _resolve_host_env_value(source)
        if value is None:
            raise ValueError(f"missing host environment variable for --agent-env-from-host: {source}")
        parsed[dest] = value
    return parsed


def _resolve_provider_env(provider: str | None) -> dict[str, str]:
    """Resolve --provider alias to env vars, reading values from .env / host env."""
    if not provider:
        return {}
    preset_key = PROVIDER_ALIASES.get(provider.lower())
    if preset_key is None:
        raise ValueError(f"unknown --provider {provider!r}; choices: {', '.join(sorted(PROVIDER_ALIASES))}")
    preset = CLAUDE_PROVIDER_PRESETS[preset_key]
    result: dict[str, str] = dict(preset.env)
    for dest, source in preset.env_from_host.items():
        value = _resolve_host_env_value(source)
        if value is None:
            raise ValueError(
                f"--provider {provider!r} requires {source!r} but it was not found in the environment or .env files"
            )
        result[dest] = value
    return result


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value or 0.0)
    raise TypeError(f"cannot convert {type(value).__name__} to float")


def run_arm(
    task: Task,
    arm: str,
    rep: int,
    model: str,
    out_dir: Path,
    timeout: int,
    agent_command: str = "claude",
    cli_driver: str = "claude",
    agent_env: dict[str, str] | None = None,
    cli_extra_args: list[str] | tuple[str, ...] = (),
    resume_state: bool = False,
) -> ArmResult:
    assert arm in VALID_ARMS
    row_state: dict[str, object] = {}
    persistent_workspace = False
    should_resume_session = False
    if cli_driver == "claude":
        state_dir = _row_state_dir(out_dir, task.id, arm, rep)
        existing_state = _load_row_state(state_dir)
        existing_workspace = Path(str(existing_state.get("workspace", "")))
        has_saved_state = bool(existing_state.get("session_id")) and existing_workspace.is_dir()
        row_state = _ensure_claude_row_state(out_dir, task.id, arm, rep)
        ws = prepare_workspace(task, Path(str(row_state["workspace"])))
        persistent_workspace = True
        should_resume_session = resume_state and has_saved_state
    elif cli_driver == "atelier-run":
        workspace_path = out_dir / "workspaces" / f"{task.id}_{arm}_rep{rep}"
        ws = prepare_workspace(task, workspace_path)
        persistent_workspace = True
    else:
        ws = prepare_workspace(task)
    if cli_driver not in CLI_DRIVERS:
        raise ValueError(f"unsupported cli driver: {cli_driver}")
    flow_path = out_dir / f"{task.id}_{arm}_rep{rep}.flow"
    proxy_supported = cli_driver in {"claude", "atelier-run"}
    port = _free_port() if proxy_supported else 0
    mitm = (
        subprocess.Popen(
            [
                "uv",
                "run",
                "--project",
                str(REPO_ROOT / "benchmarks"),
                "mitmdump",
                "-w",
                str(flow_path),
                "--listen-port",
                str(port),
                "-s",
                str(REPO_ROOT / "benchmarks" / "codebench" / "rate_limit.py"),
                "-q",
            ],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proxy_supported
        else None
    )
    try:
        if proxy_supported and not _wait_port(port):
            raise RuntimeError("mitmdump did not start")
        env = dict(os.environ)
        env.update(agent_env or {})
        # Always expose the workspace root so MCP tools and shell commands can
        # resolve relative paths without guessing.
        env.setdefault("CLAUDE_WORKSPACE_ROOT", str(ws))
        # For Python workspaces: if a .venv was created by setup_cmds, activate
        # it so all python/pytest commands in the workspace use the right env.
        ws_venv = ws / ".venv"
        if ws_venv.is_dir() and task.language == "python":
            venv_bin = str(ws_venv / "bin")
            env["VIRTUAL_ENV"] = str(ws_venv)
            env["PATH"] = venv_bin + os.pathsep + env.get("PATH", os.environ.get("PATH", ""))
        if proxy_supported:
            env["HTTPS_PROXY"] = f"http://127.0.0.1:{port}"
            env["HTTP_PROXY"] = f"http://127.0.0.1:{port}"
            env["NODE_EXTRA_CA_CERTS"] = str(CA_CERT)
            env["SSL_CERT_FILE"] = str(CA_CERT)
            env["REQUESTS_CA_BUNDLE"] = str(CA_CERT)
            env["AWS_CA_BUNDLE"] = str(CA_CERT)
        temp_paths: list[Path] = []
        if cli_driver == "claude":
            cmd = build_driver_command(
                cli_driver=cli_driver,
                prompt="Continue from where you left off." if should_resume_session else task.prompt(),
                model=model,
                workspace=str(ws),
                agent_command=agent_command,
                extra_args=cli_extra_args,
            )
            if arm in {"baseline", "atelier"}:
                # Contamination-free config: real subscription auth, but no
                # globally-installed plugins/hooks/MCP. The ONLY A/B difference
                # is then the Atelier MCP toolset + CLAUDE.md, not ambient host
                # state. Persisted next to the workspace so --resume still finds
                # the prior session transcript.
                config_dir = _make_baseline_config(
                    Path(str(row_state["workspace"])).parent / f"claude-config-{arm}" if row_state else None
                )
                env["CLAUDE_CONFIG_DIR"] = str(config_dir)
            if row_state:
                session_id = str(row_state["session_id"])
                cmd += ["--resume" if should_resume_session else "--session-id", session_id]
                cmd += ["--add-dir", str(ws)]
            if arm == "baseline":
                # Bare baseline: stock Claude Code with no injected CLAUDE.md and no
                # MCP servers. The comparison is the full Atelier agent vs a vanilla
                # Claude Code session, persona and all.
                cmd.extend(["--mcp-config", json.dumps(EMPTY_MCP), "--strict-mcp-config"])
            if arm == "atelier":
                # Load the generated Claude plugin and run its real coding
                # agent. The agent definition owns its prompt, MCP wiring, hooks,
                # and native-tool restrictions.
                cmd.extend(_atelier_claude_agent_args())
        elif cli_driver == "atelier-run":
            # Direct owned-session arm: Atelier owns prompt assembly, model routing,
            # caching, and the executable tool loop on the caller's API credentials.
            # The retained workspace is validated like every other coding arm.
            cmd = ["atelier", "run", "start", task.prompt(), "--yolo"]
            if model:
                cmd += ["--model", model]
            cmd += list(cli_extra_args)
        else:
            raise ValueError(f"unsupported cli driver: {cli_driver}")
        started = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ws),
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            wall_duration_ms = int((time.time() - started) * 1000)
            # Stop the proxy first so the .flow file holds every completed
            # round-trip before we read token usage back out of it.
            if mitm is not None:
                mitm.terminate()
                with contextlib.suppress(Exception):
                    mitm.wait(timeout=5)
                mitm = None
            stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
            excerpt = f"timed out after {timeout}s"
            if stderr_text.strip():
                excerpt = f"{excerpt}\n\n[stderr]\n{stderr_text.strip()}"
            res = _recover_flow_result(flow_path, task.id, arm, rep, model, wall_duration_ms, excerpt, timed_out=True)
            res.workspace = str(ws)
            return _apply_result_validity(task, res)
        wall_duration_ms = int((time.time() - started) * 1000)
        res = _parse_cli_result(proc.stdout, flow_path, task.id, arm, rep, cli_driver, wall_duration_ms)
        if not res.ok and proc.stderr.strip():
            diagnostics = proc.stderr.strip()
            if res.result_excerpt:
                res.result_excerpt = f"{res.result_excerpt}\n\n[stderr]\n{diagnostics}"[-4000:]
            else:
                res.result_excerpt = diagnostics[-4000:]
        res.workspace = str(ws)
        return _apply_result_validity(task, res)
    finally:
        if mitm is not None:
            mitm.terminate()
            with contextlib.suppress(Exception):
                mitm.wait(timeout=5)
        if not persistent_workspace:
            shutil.rmtree(ws, ignore_errors=True)
        for temp_path in locals().get("temp_paths", []):
            shutil.rmtree(temp_path, ignore_errors=True)


def _task_description(task: Task) -> str:
    config_path = task.prompt_path().parent / "config.yaml"
    if not config_path.exists():
        return ""
    return config_path.read_text(encoding="utf-8")[:2000]


def _judge_prompt(task: Task, result: ArmResult) -> str:
    return f"""You are grading an CodeBench response.

Return ONLY compact JSON with these keys:
{{"correct": boolean, "score": number, "reason": string}}

Scoring:
- 1.0 means the response fully satisfies the task.
- 0.7 means mostly correct but incomplete or missing verification details.
- 0.4 means partially relevant but unlikely to solve the task.
- 0.0 means wrong, empty, or not responsive.

Task id: {task.id}
Task language: {task.language}
Task config:
{_task_description(task)}

Task prompt:
{task.prompt()}

Candidate response:
{result.result_excerpt}
"""


def judge_results(
    results: list[ArmResult],
    *,
    judge_model: str,
    judge_agent_command: str,
    timeout: int,
    agent_env: dict[str, str] | None = None,
) -> None:
    for result in results:
        if result.judge_model == "verify":
            continue  # already graded by an objective per-task verify command
        if not result.ok:
            result.correct = False
            result.score = 0.0
            result.judge_model = judge_model
            result.judge_reason = "runtime failure"
            continue
        task = BY_ID.get(result.task)
        if task is None:
            result.correct = False
            result.score = 0.0
            result.judge_model = judge_model
            result.judge_reason = f"unknown task {result.task}"
            continue
        try:
            prompt = _judge_prompt(task, result)
            cmd = build_driver_command(
                cli_driver="claude",
                prompt=prompt,
                model=judge_model,
                workspace=str(REPO_ROOT),
                agent_command=judge_agent_command,
            )
            completed = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                env={**os.environ, **(agent_env or {})},
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or "").strip()[:300])
            text = str(json.loads(completed.stdout).get("result", ""))
            parsed = _parse_judge_json(text)
            result.correct = bool(parsed.get("correct", False))
            result.score = max(0.0, min(1.0, _as_float(parsed.get("score", 0.0) or 0.0)))
            result.judge_model = judge_model
            result.judge_reason = str(parsed.get("reason", ""))[:300]
        except Exception as exc:
            result.correct = False
            result.score = 0.0
            result.judge_model = judge_model
            result.judge_reason = f"judge error: {exc}"[:300]


def _parse_judge_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("judge returned non-object JSON")
    return parsed


def _normalize_model_usage(usage: dict[str, object]) -> dict[str, int]:
    """Map one model's usage dict onto canonical token-component keys.

    Claude's ``modelUsage`` block spells the components in camelCase
    (``inputTokens``, ``cacheReadInputTokens`` ...); already-normalized dicts use
    snake_case (``input``, ``cache_read`` ...). Read both spellings so the
    per-component cost breakdown is never silently zeroed by a key mismatch
    (the bug that printed ``- input: $0.0000`` while total cost was non-zero).
    """
    aliases: dict[str, tuple[str, ...]] = {
        "input": ("input", "inputTokens", "input_tokens"),
        "output": ("output", "outputTokens", "output_tokens"),
        "cache_read": ("cache_read", "cacheReadInputTokens", "cache_read_input_tokens"),
        "cache_write": ("cache_write", "cacheCreationInputTokens", "cache_creation_input_tokens"),
        "thinking": ("thinking", "thinkingTokens", "thinking_tokens"),
    }
    normalized: dict[str, int] = {}
    for canon, keys in aliases.items():
        value = 0
        for key in keys:
            raw = usage.get(key)
            if isinstance(raw, bool):
                continue
            if isinstance(raw, (int, float)):
                value = int(raw)
                break
        normalized[canon] = value
    return normalized


def _agg(results: list[ArmResult], arm: str) -> dict[str, Any]:
    rs = [r for r in results if r.arm == arm]
    judged = [r for r in rs if r.score is not None]

    aggregated_model_usage: dict[str, dict[str, int]] = {}
    for r in rs:
        for model, usage in r.model_usage.items():
            if model not in aggregated_model_usage:
                aggregated_model_usage[model] = {
                    "input": 0,
                    "output": 0,
                    "cache_read": 0,
                    "cache_write": 0,
                    "thinking": 0,
                }
            normalized = _normalize_model_usage(usage)
            for k in ["input", "output", "cache_read", "cache_write", "thinking"]:
                aggregated_model_usage[model][k] += normalized[k]

    return {
        "runs": len(rs),
        "ok": sum(1 for r in rs if r.ok),
        "valid": sum(1 for r in rs if r.valid),
        "correct": sum(1 for r in rs if r.correct is True),
        "avg_score": round(sum(float(r.score or 0.0) for r in judged) / len(judged), 3) if judged else 0.0,
        "cost_usd": round(sum(r.cost_usd for r in rs), 4),
        "duration_ms": sum(r.duration_ms for r in rs),
        "output_tokens": sum(r.output_tokens for r in rs),
        "input_tokens": sum(r.input_tokens for r in rs),
        "cache_read_tokens": sum(r.cache_read_tokens for r in rs),
        "cache_creation_tokens": sum(r.cache_creation_tokens for r in rs),
        "thinking_tokens": sum(r.thinking_tokens for r in rs),
        "num_turns": sum(r.num_turns for r in rs),
        "timed_out": sum(1 for r in rs if r.timed_out),
        "saved_usd": round(sum(r.saved_usd for r in rs), 4),
        "saved_tokens": sum(r.saved_tokens for r in rs),
        "model_usage": aggregated_model_usage,
    }


def report(results: list[ArmResult]) -> str:
    arms = _ordered_arms(results)
    aggregates = {arm: _agg(results, arm) for arm in arms}
    baseline = aggregates.get("baseline")
    lines = [
        "",
        "=== CodeBench head-to-head ===",
        f"{'metric':<22}" + "".join(f"{arm:>14}" for arm in arms),
    ]

    def row(label: str, values: list[float], format: str = ",.4f") -> str:
        rendered = [f"{value:{format}}" for value in values]
        return f"{label:<22}" + "".join(f"{value:>14}" for value in rendered)

    lines.append(row("cost_usd", [_as_float(aggregates[arm]["cost_usd"]) for arm in arms]))

    # Detailed cost breakdown
    for arm in arms:
        agg = aggregates[arm]
        model_usage = agg.get("model_usage", {})
        if not model_usage:
            continue

        total_breakdown = {
            "input": 0.0,
            "output": 0.0,
            "cache_read": 0.0,
            "cache_write": 0.0,
            "thinking": 0.0,
        }
        for model_id, usage in model_usage.items():
            breakdown = usage_cost_breakdown_usd(
                model_id,
                input_tokens=usage.get("input", 0),
                output_tokens=usage.get("output", 0),
                cache_read_tokens=usage.get("cache_read", 0),
                cache_write_tokens=usage.get("cache_write", 0),
                thinking_tokens=usage.get("thinking", 0),
            )
            for k in total_breakdown:
                total_breakdown[k] += breakdown.get(k, 0.0)

        lines.append(
            "  - input        : "
            + "".join(f"${total_breakdown['input']:>13.4f}" if a == arm else f"{'':>14}" for a in arms)
        )
        lines.append(
            "  - output       : "
            + "".join(f"${total_breakdown['output']:>13.4f}" if a == arm else f"{'':>14}" for a in arms)
        )
        if total_breakdown["cache_read"] > 0:
            lines.append(
                "  - cache_read   : "
                + "".join(f"${total_breakdown['cache_read']:>13.4f}" if a == arm else f"{'':>14}" for a in arms)
            )
        if total_breakdown["cache_write"] > 0:
            lines.append(
                "  - cache_write  : "
                + "".join(f"${total_breakdown['cache_write']:>13.4f}" if a == arm else f"{'':>14}" for a in arms)
            )
        if total_breakdown["thinking"] > 0:
            lines.append(
                "  - thinking     : "
                + "".join(f"${total_breakdown['thinking']:>13.4f}" if a == arm else f"{'':>14}" for a in arms)
            )

    lines.append(row("duration_ms", [_as_float(aggregates[arm]["duration_ms"]) for arm in arms], ",.0f"))
    lines.append(row("num_turns", [_as_float(aggregates[arm]["num_turns"]) for arm in arms], ",.0f"))
    lines.append(row("input_tokens", [_as_float(aggregates[arm]["input_tokens"]) for arm in arms], ",.0f"))
    lines.append(
        row(
            "cache_read_tokens",
            [_as_float(aggregates[arm]["cache_read_tokens"]) for arm in arms],
            ",.0f",
        )
    )
    lines.append(
        row(
            "cache_write_tokens",
            [_as_float(aggregates[arm]["cache_creation_tokens"]) for arm in arms],
            ",.0f",
        )
    )
    lines.append(
        row(
            "thinking_tokens",
            [_as_float(aggregates[arm]["thinking_tokens"]) for arm in arms],
            ",.0f",
        )
    )
    lines.append(row("output_tokens", [_as_float(aggregates[arm]["output_tokens"]) for arm in arms], ",.0f"))
    lines.append(row("saved_usd", [_as_float(aggregates[arm]["saved_usd"]) for arm in arms]))
    lines.append(row("saved_tokens", [_as_float(aggregates[arm]["saved_tokens"]) for arm in arms], ",.0f"))
    if baseline:
        lines.append("")
        for arm in arms:
            if arm == "baseline":
                continue
            current = aggregates[arm]
            cost_save = _savings_pct(_as_float(baseline["cost_usd"]), _as_float(current["cost_usd"]))
            time_save = _savings_pct(
                _as_float(baseline["duration_ms"]),
                _as_float(current["duration_ms"]),
            )
            lines.append(f"{arm} cost saving : {cost_save:+.1f}%  (Vix target ~47-50%)")
            lines.append(f"{arm} time saving : {time_save:+.1f}%  (Vix target ~40%)")
    ok_parts = [f"{arm} {aggregates[arm]['ok']}/{aggregates[arm]['runs']}" for arm in arms]
    lines.append(f"Runs ok     : {'  '.join(ok_parts)}")
    valid_parts = [f"{arm} {aggregates[arm]['valid']}/{aggregates[arm]['runs']}" for arm in arms]
    lines.append(f"Valid       : {'  '.join(valid_parts)}")
    if any(aggregates[arm]["timed_out"] for arm in arms):
        timeout_parts = [f"{arm} {aggregates[arm]['timed_out']}/{aggregates[arm]['runs']}" for arm in arms]
        lines.append(f"Timeouts    : {'  '.join(timeout_parts)}")
    if any(_is_content_invalid(result) for result in results):
        lines.append("Validity    : invalid/off-topic runs detected; cost/token comparisons are not meaningful.")
    if any(result.score is not None for result in results):
        score_parts = [
            f"{arm} {aggregates[arm]['correct']}/{aggregates[arm]['runs']} avg={aggregates[arm]['avg_score']}"
            for arm in arms
        ]
        lines.append(f"Correct     : {'  '.join(score_parts)}")
    return "\n".join(lines)


def _detail_rows(results: list[ArmResult]) -> list[dict[str, object]]:
    rows = [asdict(result) for result in results]
    for row in rows:
        row.pop("model_usage", None)
        row.pop("workspace", None)
    return rows


def _summary_rows(results: list[ArmResult]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    baseline = _summary_row(results, "baseline") if any(result.arm == "baseline" for result in results) else None
    for arm in _ordered_arms(results):
        row = _summary_row(results, arm)
        if baseline is None:
            row.update(_empty_savings_columns())
        else:
            row.update(
                {
                    "cost_savings_vs_baseline_pct": _savings_pct(
                        _as_float(baseline["cost_usd"]),
                        _as_float(row["cost_usd"]),
                    ),
                    "duration_savings_vs_baseline_pct": _savings_pct(
                        _as_float(baseline["duration_ms"]),
                        _as_float(row["duration_ms"]),
                    ),
                    "input_token_savings_vs_baseline_pct": _savings_pct(
                        _as_float(baseline["input_tokens"]),
                        _as_float(row["input_tokens"]),
                    ),
                    "output_token_savings_vs_baseline_pct": _savings_pct(
                        _as_float(baseline["output_tokens"]),
                        _as_float(row["output_tokens"]),
                    ),
                }
            )
        rows.append(row)
    return rows


def _ordered_arms(results: list[ArmResult]) -> list[str]:
    seen = {result.arm for result in results}
    ordered = [arm for arm in VALID_ARMS if arm in seen]
    ordered.extend(sorted(seen - set(VALID_ARMS)))
    return ordered


def _summary_row(results: list[ArmResult], arm: str) -> dict[str, object]:
    arm_results = [result for result in results if result.arm == arm]
    return {
        "arm": arm,
        "runs": len(arm_results),
        "ok_runs": sum(1 for result in arm_results if result.ok),
        "failed_runs": sum(1 for result in arm_results if not result.ok),
        "valid_runs": sum(1 for result in arm_results if result.valid),
        "correct_runs": sum(1 for result in arm_results if result.correct is True),
        "avg_score": (
            round(sum(float(result.score or 0.0) for result in judged) / len(judged), 3)
            if (judged := [result for result in arm_results if result.score is not None])
            else ""
        ),
        "cost_usd": round(sum(result.cost_usd for result in arm_results), 4),
        "duration_ms": sum(result.duration_ms for result in arm_results),
        "duration_api_ms": sum(result.duration_api_ms for result in arm_results),
        "input_tokens": sum(result.input_tokens for result in arm_results),
        "cache_read_tokens": sum(result.cache_read_tokens for result in arm_results),
        "cache_creation_tokens": sum(result.cache_creation_tokens for result in arm_results),
        "output_tokens": sum(result.output_tokens for result in arm_results),
    }


def _empty_savings_columns() -> dict[str, object]:
    return {
        "cost_savings_vs_baseline_pct": "",
        "duration_savings_vs_baseline_pct": "",
        "input_token_savings_vs_baseline_pct": "",
        "output_token_savings_vs_baseline_pct": "",
    }


def _savings_pct(baseline: float, current: float) -> float:
    return round((1 - current / baseline) * 100, 1) if baseline else 0.0


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _result_key(result: ArmResult) -> tuple[str, str, int]:
    return (result.task, result.arm, result.rep)


def _row_state_dir(out_dir: Path, task_id: str, arm: str, rep: int) -> Path:
    return out_dir / "state" / f"{task_id}_{arm}_rep{rep}"


def _load_row_state(state_dir: Path) -> dict[str, object]:
    state_path = state_dir / "state.json"
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _ensure_claude_row_state(out_dir: Path, task_id: str, arm: str, rep: int) -> dict[str, object]:
    state_dir = _row_state_dir(out_dir, task_id, arm, rep)
    state_dir.mkdir(parents=True, exist_ok=True)
    state = _load_row_state(state_dir)
    run_key = uuid.uuid5(uuid.NAMESPACE_URL, str(out_dir.resolve())).hex[:12]
    state.setdefault("session_id", str(uuid.uuid4()))
    state.setdefault(
        "workspace",
        str(PERSISTENT_WORKSPACE_ROOT / f"{out_dir.name}-{run_key}" / f"{task_id}_{arm}_rep{rep}"),
    )
    (state_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def _load_existing_results(run_dir: Path) -> list[ArmResult]:
    results_path = run_dir / "results.jsonl"
    if not results_path.exists():
        return []
    return [
        ArmResult(**json.loads(line)) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_results_jsonl(run_dir: Path, results: list[ArmResult]) -> None:
    (run_dir / "results.jsonl").write_text(
        "".join(json.dumps(asdict(result)) + "\n" for result in results),
        encoding="utf-8",
    )


def write_csv_artifacts(run_dir: Path, results: list[ArmResult]) -> None:
    _write_csv(
        run_dir / "results.csv",
        _detail_rows(results),
        [
            "task",
            "arm",
            "rep",
            "ok",
            "cost_usd",
            "duration_ms",
            "duration_api_ms",
            "num_turns",
            "input_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "thinking_tokens",
            "output_tokens",
            "models",
            "is_error",
            "timed_out",
            "result_excerpt",
            "flow_path",
            "valid",
            "validity_reason",
            "correct",
            "score",
            "judge_model",
            "judge_reason",
            "saved_usd",
            "saved_tokens",
        ],
    )
    _write_csv(
        run_dir / "summary.csv",
        _summary_rows(results),
        [
            "arm",
            "runs",
            "ok_runs",
            "failed_runs",
            "valid_runs",
            "correct_runs",
            "avg_score",
            "cost_usd",
            "duration_ms",
            "duration_api_ms",
            "input_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
            "output_tokens",
            "cost_savings_vs_baseline_pct",
            "duration_savings_vs_baseline_pct",
            "input_token_savings_vs_baseline_pct",
            "output_token_savings_vs_baseline_pct",
        ],
    )


def _run_task_rep(
    task_id: str,
    rep: int,
    *,
    arms: list[str],
    model: str,
    out_dir: Path,
    timeout: int,
    agent_command: str,
    cli_driver: str,
    agent_env: dict[str, str] | None,
    cli_extra_args: list[str] | tuple[str, ...],
    resume_state: bool,
    on_result: Callable[[ArmResult], None] | None = None,
) -> list[ArmResult]:
    task = BY_ID[task_id]
    results: list[ArmResult] = []
    for arm in arms:
        print(f"[run] {task_id} {arm} rep{rep} (model={model}, driver={cli_driver}) ...", flush=True)
        t0 = time.time()
        try:
            result = run_arm(
                task,
                arm,
                rep,
                model,
                out_dir,
                timeout,
                agent_command,
                cli_driver,
                agent_env,
                cli_extra_args,
                resume_state=resume_state,
            )
        except Exception as exc:
            result = ArmResult(
                task_id,
                arm,
                rep,
                False,
                0.0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                [],
                True,
                f"harness error: {exc}"[:200],
                "",
            )
            result = _apply_result_validity(task, result)
        wall = time.time() - t0
        if result.ok:
            status = "OK"
        elif result.timed_out:
            status = "TIMEOUT"
        else:
            status = "FAIL"
        summary = (
            f"  -> [{status}] {task_id}/{arm} rep{rep}"
            f"  cost=${result.cost_usd:.4f}"
            f"  turns={result.num_turns}"
            f"  out={result.output_tokens:,}tok"
            f"  wall={_fmt_hms(wall)}"
        )
        if not result.ok and result.result_excerpt:
            first_line = result.result_excerpt.strip().splitlines()[0][:100]
            summary += f"\n        {first_line}"
        print(summary, flush=True)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


def _run_single_arm(
    task_id: str,
    rep: int,
    arm: str,
    *,
    model: str,
    out_dir: Path,
    timeout: int,
    agent_command: str,
    cli_driver: str,
    agent_env: dict[str, str] | None,
    cli_extra_args: list[str] | tuple[str, ...],
    resume_state: bool,
    on_result: Callable[[ArmResult], None] | None = None,
) -> ArmResult:
    return _run_task_rep(
        task_id,
        rep,
        arms=[arm],
        model=model,
        out_dir=out_dir,
        timeout=timeout,
        agent_command=agent_command,
        cli_driver=cli_driver,
        agent_env=agent_env,
        cli_extra_args=cli_extra_args,
        resume_state=resume_state,
        on_result=on_result,
    )[0]


def main() -> int:
    p = argparse.ArgumentParser(description="CodeBench head-to-head runner")
    p.add_argument("tasks", nargs="*", default=["all"], metavar="TASK", help="task ids or 'all' (default: all)")
    p.add_argument("-a", "--arms", nargs="*", default=["baseline", "atelier"])
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--model", default="sonnet")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument(
        "--rate-limit-rpm",
        "--rate-limit",
        type=float,
        default=0,
        dest="rate_limit_rpm",
        help="Maximum model inference requests per minute; 0 disables throttling",
    )
    p.add_argument(
        "--rate-limit-tpm",
        type=int,
        default=0,
        help="Maximum reserved output tokens per rolling minute; 0 disables throttling",
    )
    p.add_argument("--driver", "--cli-driver", choices=CLI_DRIVERS, default="claude", dest="cli_driver")
    p.add_argument("--jobs", type=int, default=1, help="Parallel task/rep workers; arms stay serial per worker")
    p.add_argument(
        "--parallel-scope",
        choices=["task", "arm"],
        default="task",
        help="Use 'arm' only for throughput experiments; 'task' preserves fair per-task comparisons.",
    )
    p.add_argument("--judge", action="store_true", help="Score correctness with an LLM judge")
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip objective per-task verify gates (cargo test/pytest/...); they run by default",
    )
    p.add_argument("--judge-model", default=None)
    p.add_argument("--judge-agent-command", default=None)
    p.add_argument("--agent-command", default="claude", help="Claude-compatible command to run each arm")
    p.add_argument(
        "--agent-env",
        action="append",
        default=[],
        help="Environment override for CLI transport in KEY=VALUE form; repeatable.",
    )
    p.add_argument(
        "--agent-env-from-host",
        action="append",
        default=[],
        help="Copy a host env var into CLI transport env as DEST_KEY=SOURCE_ENV; repeatable.",
    )
    p.add_argument(
        "--provider",
        default=None,
        metavar="PROVIDER",
        help=(
            "Cloud provider shorthand: aws/bedrock, gcp/vertex, azure, openrouter. "
            "Reads credentials from .env or the current environment automatically. "
            "Explicit --agent-env values take precedence."
        ),
    )
    p.add_argument(
        "--cli-extra-arg",
        action="append",
        default=[],
        help="Extra CLI argument passed to the selected driver; repeatable.",
    )
    p.add_argument("--bridge-command", default=None, help="Optional background bridge command to launch first")
    p.add_argument("--bridge-wait", type=float, default=3.0, help="Seconds to wait after launching the bridge")
    p.add_argument("--out", type=Path, default=None, help="directory for run artifacts")
    p.add_argument("--resume", action="store_true", help="append to existing out dir and skip done runs")
    p.add_argument(
        "--retry-failed",
        action="store_true",
        help="with --resume, rerun rows where ok is false",
    )
    p.add_argument("--report", default=None, help="path to a results dir to re-report")
    args = p.parse_args()
    if args.rate_limit_rpm < 0:
        p.error("--rate-limit must be >= 0")
    if args.rate_limit_tpm < 0:
        p.error("--rate-limit-tpm must be >= 0")
    os.environ["CODEBENCH_RATE_LIMIT_RPM"] = str(args.rate_limit_rpm)
    os.environ["CODEBENCH_RATE_LIMIT_TPM"] = str(args.rate_limit_tpm)
    if args.rate_limit_rpm > 0 and any(arm in HEAVY_ARMS for arm in args.arms):
        request_budget = args.rate_limit_rpm * args.timeout / 60.0
        if request_budget < RPM_TIMEOUT_MIN_REQUESTS:
            suggested_timeout = int(RPM_TIMEOUT_MIN_REQUESTS / args.rate_limit_rpm * 60)
            print(
                f"WARNING: --rate-limit-rpm {args.rate_limit_rpm:g} allows only "
                f"~{request_budget:.0f} model requests within --timeout {args.timeout}s. "
                f"Tool-heavy arms (atelier) routinely exceed that and will time out. "
                f"Raise --timeout to >= {suggested_timeout}s or increase --rate-limit-rpm.",
                flush=True,
            )
    agent_env = {
        **_resolve_provider_env(args.provider),
        **_parse_agent_env(args.agent_env),
        **_parse_agent_env_from_host(args.agent_env_from_host),
    }
    judge_model = args.judge_model or args.model
    judge_agent_command = args.judge_agent_command or args.agent_command
    if args.report:
        rdir = Path(args.report)
        report_results = _load_existing_results(rdir)
        if not args.no_verify:
            _apply_verify(report_results)
        if args.judge:
            judge_results(
                report_results,
                judge_model=judge_model,
                judge_agent_command=judge_agent_command,
                timeout=args.timeout,
                agent_env=agent_env,
            )
        _apply_savings(report_results)
        _write_results_jsonl(rdir, report_results)
        write_csv_artifacts(rdir, report_results)
        rep_txt = report(report_results)
        (rdir / "report.txt").write_text(rep_txt)
        print(rep_txt)
        return 0
    task_ids = [t.id for t in TASKS] if args.tasks == ["all"] else args.tasks
    run_dir = args.out if args.out is not None else RESULTS_ROOT / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Results: {run_dir.resolve()}", flush=True)
    unknown_arms = [arm for arm in args.arms if arm not in VALID_ARMS]
    if unknown_arms:
        p.error(f"unknown arm(s): {', '.join(unknown_arms)}")
    if args.jobs < 1:
        p.error("--jobs must be >= 1")
    if args.retry_failed and not args.resume:
        p.error("--retry-failed requires --resume")

    # Verify required binaries are present for the selected tasks before
    # spending time on workspace setup or model API calls.
    selected_tasks = [BY_ID[tid] for tid in task_ids if tid in BY_ID]
    if not check_prereqs(selected_tasks):
        print("Aborting: install the missing prerequisites and rerun.", flush=True)
        return 1
    bridge_command = args.bridge_command
    bridge = subprocess.Popen(shlex.split(bridge_command), cwd=str(REPO_ROOT)) if bridge_command else None
    if bridge is not None and args.bridge_wait > 0:
        time.sleep(args.bridge_wait)
    existing_results = _load_existing_results(run_dir) if args.resume else []
    if args.retry_failed:
        retry_count = sum(1 for result in existing_results if not result.ok)
        results = [result for result in existing_results if result.ok]
        print(f"Retrying failed rows: {retry_count}", flush=True)
    else:
        results = existing_results
    completed = {_result_key(result) for result in results}
    jl_mode = "w" if args.retry_failed else ("a" if args.resume else "w")
    jl = (run_dir / "results.jsonl").open(jl_mode, encoding="utf-8")
    if jl_mode == "w":
        for res in results:
            jl.write(json.dumps(asdict(res)) + "\n")
        jl.flush()
    result_lock = threading.Lock()

    def record_result(res: ArmResult) -> None:
        with result_lock:
            if _result_key(res) in completed:
                return
            results.append(res)
            completed.add(_result_key(res))
            jl.write(json.dumps(asdict(res)) + "\n")
            jl.flush()

    try:
        pending_trials: list[tuple[str, int, list[str]]] = []
        pending_arms: list[tuple[str, int, str]] = []
        for tid in task_ids:
            for rep in range(args.reps):
                missing_arms = [arm for arm in args.arms if (tid, arm, rep) not in completed]
                if not missing_arms:
                    for arm in args.arms:
                        print(f"[skip] {tid} {arm} rep{rep} already recorded", flush=True)
                    continue
                for arm in args.arms:
                    if (tid, arm, rep) in completed:
                        print(f"[skip] {tid} {arm} rep{rep} already recorded", flush=True)
                pending_trials.append((tid, rep, missing_arms))
                pending_arms.extend((tid, rep, arm) for arm in missing_arms)

        if args.jobs == 1 and args.parallel_scope == "task":
            for tid, rep, pending_arms in pending_trials:
                _run_task_rep(
                    tid,
                    rep,
                    arms=pending_arms,
                    model=args.model,
                    out_dir=run_dir,
                    timeout=args.timeout,
                    agent_command=args.agent_command,
                    cli_driver=args.cli_driver,
                    agent_env=agent_env,
                    cli_extra_args=args.cli_extra_arg,
                    resume_state=args.resume,
                    on_result=record_result,
                )
        elif args.parallel_scope == "task":
            with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                futures = {
                    executor.submit(
                        _run_task_rep,
                        tid,
                        rep,
                        arms=pending_arms,
                        model=args.model,
                        out_dir=run_dir,
                        timeout=args.timeout,
                        agent_command=args.agent_command,
                        cli_driver=args.cli_driver,
                        agent_env=agent_env,
                        cli_extra_args=args.cli_extra_arg,
                        resume_state=args.resume,
                        on_result=record_result,
                    ): (tid, rep)
                    for tid, rep, pending_arms in pending_trials
                }
                for future in as_completed(futures):
                    future.result()
        elif args.jobs == 1:
            for tid, rep, arm in pending_arms:
                res = _run_single_arm(
                    tid,
                    rep,
                    arm,
                    model=args.model,
                    out_dir=run_dir,
                    timeout=args.timeout,
                    agent_command=args.agent_command,
                    cli_driver=args.cli_driver,
                    agent_env=agent_env,
                    cli_extra_args=args.cli_extra_arg,
                    resume_state=args.resume,
                    on_result=record_result,
                )
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as executor:
                futures = {
                    executor.submit(
                        _run_single_arm,
                        tid,
                        rep,
                        arm,
                        model=args.model,
                        out_dir=run_dir,
                        timeout=args.timeout,
                        agent_command=args.agent_command,
                        cli_driver=args.cli_driver,
                        agent_env=agent_env,
                        cli_extra_args=args.cli_extra_arg,
                        resume_state=args.resume,
                        on_result=record_result,
                    ): (tid, rep, arm)
                    for tid, rep, arm in pending_arms
                }
            for future in as_completed(futures):
                future.result()
    finally:
        jl.close()
        if bridge is not None and bridge.poll() is None:
            bridge.terminate()
            with contextlib.suppress(Exception):
                bridge.wait(timeout=10)
    if not args.no_verify:
        _apply_verify(results)
    if args.judge:
        judge_results(
            results,
            judge_model=judge_model,
            judge_agent_command=judge_agent_command,
            timeout=args.timeout,
            agent_env=agent_env,
        )
    _apply_savings(results)
    _write_results_jsonl(run_dir, results)
    write_csv_artifacts(run_dir, results)
    rep_txt = report(results)
    (run_dir / "report.txt").write_text(rep_txt)
    print(rep_txt)
    print(f"\nResults: {run_dir}")
    if any(_is_content_invalid(result) for result in results):
        return 2
    if any(not result.ok for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
