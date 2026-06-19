"""In-container agent runner for Multi-SWE-bench instances (option A).

The agent (Claude Code, optionally + Atelier) runs INSIDE each instance's
Docker image -- which carries the real toolchain -- against the repo checked
out at ``base_sha``. The produced git diff is extracted as the agent's
``fix_patch`` and the run is parsed into a run.py ``ArmResult`` so every
existing savings / report / CSV path applies unchanged.

The two arms differ only in the overlay contents + the claude flags:
  baseline -> vanilla Claude Code (default persona, empty MCP)
  atelier  -> Claude Code + the Atelier plugin (--plugin-dir, --agent atelier:code)
That is the vanilla-vs-Atelier isolation, same model, same task.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

from benchmarks.codebench.run import (
    ATELIER_CLAUDE_PLUGIN_ROOT,
    CA_CERT,
    REPO_ROOT,
    ArmResult,
    _free_port,
    _parse_claude_result,
    _wait_port,
)


class RunnableInstance(Protocol):
    """Minimal instance shape the runner needs (Multi-SWE-bench or SWE-bench)."""

    instance_id: str
    image: str
    problem_statement: str


ENTRY_SCRIPT = Path(__file__).parent / "incontainer_entry.sh"
# Pre-warmed tiktoken cache bind-mounted into the atelier container. The Atelier
# MCP server loads cl100k_base at import (repo_map.budget); without a warmed
# cache it downloads from openaipublic.blob, which dies under the benchmark proxy
# (mitm CA absent from Python's trust store) and crashes the server -> zero
# Atelier tools reach the agent. Warmed by _ensure_tiktoken_cache().
TIKTOKEN_CACHE_HOST = Path(__file__).parent / ".tiktoken-cache"
OVERLAY_NAMESPACE = "codebench-overlay"
_DIFF_BEGIN = "<<<CODEBENCH_DIFF_BEGIN>>>"
_DIFF_END = "<<<CODEBENCH_DIFF_END>>>"

# Persona per arm for the "code" capability (mirrors run.ARM_SPECS).
_ARM_AGENT: dict[str, str | None] = {"baseline": None, "atelier": "atelier:code"}

# Installed into every overlay: Node + the claude CLI on top of the instance image.
_BASELINE_INSTALL = r"""
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates gnupg git
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y --no-install-recommends nodejs
npm install -g @anthropic-ai/claude-code
npm cache clean --force
rm -rf /var/lib/apt/lists/*
"""

# Atelier arm only: install the atelier CLI from the mounted repo (skip mypyc
# for a fast pure-Python build) onto PATH so the plugin's MCP server
# (`atelier mcp --host claude`) resolves exactly as it does on the host.
# Extras go on the path requirement; UV_TOOL_BIN_DIR puts the entrypoints on PATH.
_ATELIER_INSTALL = r"""
set -e
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
ATELIER_SKIP_MYPYC=1 UV_TOOL_BIN_DIR=/usr/local/bin /usr/local/bin/uv tool install --force "/opt/atelier[mcp,smart,parsers,rename]"
"""


def _run(cmd: list[str], *, timeout: float | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout, check=False)


def _ensure_tiktoken_cache() -> None:
    """Warm the bind-mounted tiktoken cache (idempotent; a hit is a no-op).

    The in-container Atelier MCP server loads cl100k_base at import; with this
    cache present it never reaches the network, which would otherwise crash the
    server under the benchmark proxy. Warms with the atelier venv (which carries
    tiktoken) so a fresh clone / CI run can't silently regress.
    """
    if TIKTOKEN_CACHE_HOST.exists() and any(TIKTOKEN_CACHE_HOST.iterdir()):
        return
    TIKTOKEN_CACHE_HOST.mkdir(parents=True, exist_ok=True)
    venv_py = REPO_ROOT / ".venv" / "bin" / "python3"
    py = str(venv_py) if venv_py.exists() else sys.executable
    subprocess.run(
        [py, "-c", "import tiktoken; tiktoken.get_encoding('cl100k_base')"],
        env={**os.environ, "TIKTOKEN_CACHE_DIR": str(TIKTOKEN_CACHE_HOST)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def image_exists(tag: str) -> bool:
    return _run(["docker", "image", "inspect", tag]).returncode == 0


def _safe(base_image: str) -> str:
    import re

    return re.sub(r"[^a-z0-9_.-]+", "_", base_image.lower()).strip("_")


def overlay_tag(base_image: str, *, atelier: bool) -> str:
    return f"{OVERLAY_NAMESPACE}/{_safe(base_image)}:{'atelier' if atelier else 'baseline'}"


def ensure_base_image(image: str, *, timeout: float = 1800) -> None:
    if image_exists(image):
        return
    proc = _run(["docker", "pull", image], timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"docker pull {image} failed: {proc.stderr[-400:]}")


def ensure_overlay(base_image: str, *, atelier: bool, build_timeout: float = 3600) -> str:
    """Build (once, then cache) the harness overlay for *base_image*.

    The atelier overlay layers on the baseline overlay (which already carries
    Node + claude), so node/claude install once per base image and the atelier
    build only adds the atelier CLI.
    """
    tag = overlay_tag(base_image, atelier=atelier)
    if image_exists(tag):
        return tag
    if atelier:
        parent = ensure_overlay(base_image, atelier=False)
        install = _ATELIER_INSTALL
        mounts = ["-v", f"{REPO_ROOT}:/opt/atelier:ro"]
    else:
        ensure_base_image(base_image)
        parent = base_image
        install = _BASELINE_INSTALL
        mounts = []
    builder = f"overlay_build_{_safe(base_image)}_{'atelier' if atelier else 'baseline'}"
    _run(["docker", "rm", "-f", builder])
    start = ["docker", "run", "-d", "--name", builder, *mounts, parent, "sleep", "infinity"]
    proc = _run(start)
    if proc.returncode != 0:
        raise RuntimeError(f"overlay container start failed: {proc.stderr[-400:]}")
    try:
        proc = _run(["docker", "exec", builder, "bash", "-lc", install], timeout=build_timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"overlay install failed for {tag}:\n{proc.stdout[-800:]}\n{proc.stderr[-800:]}")
        if _run(["docker", "commit", builder, tag]).returncode != 0:
            raise RuntimeError(f"docker commit {tag} failed")
    finally:
        _run(["docker", "rm", "-f", builder])
    return tag


def _start_proxy(port: int, flow_path: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT / "benchmarks"),
            "mitmdump",
            "-w",
            str(flow_path),
            "--listen-host",
            "0.0.0.0",
            "--listen-port",
            str(port),
            "-q",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_proxy(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    proc.terminate()
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)


def _split_output(stdout: str) -> tuple[str, str]:
    """Split container stdout into (claude_json, diff_text)."""
    idx = stdout.find(_DIFF_BEGIN)
    head = stdout if idx == -1 else stdout[:idx]
    diff = ""
    if idx != -1:
        rest = stdout[idx + len(_DIFF_BEGIN) :]
        end = rest.find(_DIFF_END)
        diff = (rest if end == -1 else rest[:end]).strip("\n")
        if diff:
            # git apply requires a newline-terminated patch; the strip above
            # removes the trailing newline and makes the final hunk unparseable
            # ('corrupt patch at line N'), which silently fails every grade.
            diff += "\n"
    brace = head.find("{")
    claude_json = (head[brace:] if brace != -1 else head).strip()
    return claude_json, diff


def _docker_run_cmd(
    instance: RunnableInstance,
    arm: str,
    *,
    overlay: str,
    model: str,
    max_turns: int,
    proxy_port: int,
    prompt_path: Path,
    agent_env: dict[str, str],
) -> list[str]:
    cmd = [
        "docker",
        "run",
        "--rm",
        "--add-host=host.docker.internal:host-gateway",
        "-v",
        f"{ENTRY_SCRIPT}:/mnt/run.sh:ro",
        "-v",
        f"{prompt_path}:/mnt/prompt.txt:ro",
        "-v",
        f"{CA_CERT}:/mnt/mitm.pem:ro",
    ]
    if arm == "atelier":
        cmd += ["-v", f"{ATELIER_CLAUDE_PLUGIN_ROOT}:/mnt/plugin:ro"]
        cmd += ["-v", f"{TIKTOKEN_CACHE_HOST}:/opt/tiktoken-cache:ro"]
    env: dict[str, str] = {
        "IS_SANDBOX": "1",
        "NODE_EXTRA_CA_CERTS": "/mnt/mitm.pem",
        "HTTPS_PROXY": f"http://host.docker.internal:{proxy_port}",
        "HTTP_PROXY": f"http://host.docker.internal:{proxy_port}",
        "CODEBENCH_ARM": arm,
        "CODEBENCH_MODEL": model,
        "CODEBENCH_MAX_TURNS": str(max_turns),
    }
    # SWE-bench images carry the repo at /testbed; pin it so the entry script
    # never picks a stray .git (e.g. under site-packages). Multi-SWE instances
    # leave this unset and the entry script auto-discovers the repo.
    repo_dir = getattr(instance, "repo_dir", None)
    if repo_dir:
        env["CODEBENCH_REPO_DIR"] = str(repo_dir)
    agent = _ARM_AGENT.get(arm)
    if agent:
        env["CODEBENCH_AGENT"] = agent
    if arm == "atelier":
        # Point tiktoken at the bind-mounted pre-warmed cache so the MCP server
        # never reaches the network at import (see TIKTOKEN_CACHE_HOST).
        env["TIKTOKEN_CACHE_DIR"] = "/opt/tiktoken-cache"
    env.update(agent_env)
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [overlay, "bash", "/mnt/run.sh"]
    return cmd


def run_in_container(
    instance: RunnableInstance,
    arm: str,
    rep: int,
    *,
    model: str,
    out_dir: Path,
    timeout: int,
    agent_env: dict[str, str] | None = None,
    max_turns: int = 50,
    overlay: str | None = None,
) -> ArmResult:
    """Run one (instance, arm, rep) in its container; return a run.py ArmResult.

    Side effect: writes ``<id>_<arm>_rep<rep>.patch`` (the agent's diff) and
    ``...flow`` (wire capture) under *out_dir*; the grader reads the patch.
    """
    agent_env = agent_env or {}
    if arm == "atelier":
        _ensure_tiktoken_cache()
    overlay = overlay or ensure_overlay(instance.image, atelier=(arm == "atelier"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{instance.instance_id}_{arm}_rep{rep}"
    flow_path = out_dir / f"{stem}.flow"
    patch_path = out_dir / f"{stem}.patch"
    prompt_path = out_dir / f"{stem}.prompt.txt"
    prompt_path.write_text(instance.problem_statement, encoding="utf-8")

    port = _free_port()
    proxy = _start_proxy(port, flow_path)
    started = time.time()
    timed_out = False
    stdout = ""
    stderr = ""
    try:
        if not _wait_port(port):
            raise RuntimeError("mitmdump did not start")
        cmd = _docker_run_cmd(
            instance,
            arm,
            overlay=overlay,
            model=model,
            max_turns=max_turns,
            proxy_port=port,
            prompt_path=prompt_path,
            agent_env=agent_env,
        )
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    finally:
        _stop_proxy(proxy)
    wall_ms = int((time.time() - started) * 1000)

    claude_json, diff = _split_output(stdout)
    patch_path.write_text(diff, encoding="utf-8")
    result = _parse_claude_result(claude_json, flow_path, instance.instance_id, arm, rep)
    if result.duration_ms == 0:
        result.duration_ms = wall_ms
    if result.duration_api_ms == 0:
        result.duration_api_ms = wall_ms
    result.timed_out = timed_out
    if timed_out:
        result.is_error = True
        result.ok = False
        result.result_excerpt = (f"timed out after {timeout}s\n{stderr.strip()}")[:4000]
    elif not result.ok and stderr.strip():
        result.result_excerpt = (result.result_excerpt + "\n[stderr]\n" + stderr.strip())[-4000:]
    return result
