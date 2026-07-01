"""Atelier Harbor agent adapters.

Implements Harbor's ``BaseInstalledAgent`` interface so Atelier can be
evaluated on any Harbor-registered dataset (terminal-bench-2, etc.).

Run with:

    harbor run -d "terminal-bench/terminal-bench-2" \\
        --agent-import-path benchmarks.harbor.atelier_agent:AtelierHarborAgent

Or via the CLI:

    atelier eval harbor --limit 5
    atelier eval harbor --agent atelier-bedrock --limit 5
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from pathlib import Path
from typing import Any

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# ── Constants ─────────────────────────────────────────────────────────────────

_ATELIER_VERSION = os.environ.get("ATELIER_BENCH_VERSION", "latest")
_DEFAULT_MODEL = os.environ.get("ATELIER_BENCH_MODEL", "claude-sonnet-4-5")
# Reasoning effort passed to `claude --effort`. Anthropic's official Opus 4.8
# Terminal-Bench 2.1 runs use "high" effort (Opus 4.8 System Card, sec 8.3);
# overridable via ATELIER_BENCH_EFFORT.
_DEFAULT_EFFORT = os.environ.get("ATELIER_BENCH_EFFORT", "high")
# Tools disabled for every benchmark run via `claude --disallowedTools` (this
# REMOVES their schemas from the request, so it also trims tokens). No-ask
# (AskUserQuestion/ExitPlanMode) stops the headless agent stalling on a prompt;
# no-web (WebFetch/WebSearch/mcp__atelier__web_fetch) is the agent-layer answer-
# fetch guard; Workflow/ScheduleWakeup are the heavy tools `bare` strips for
# token overhead -- we strip them here so the `auto` agent stays token-light
# without needing the `bare` variant (whose coding guide says "if confused ask").
# Residual: the agent's shell can still curl -- close that with the network proxy
# when full hermeticity is required.
_DISALLOWED_TOOLS = os.environ.get(
    "ATELIER_BENCH_DISALLOWED_TOOLS",
    # Mirrors codebench/incontainer_entry.sh exactly: no-ask, no-plan, no-web,
    # no-orchestration. Keeps conditions identical to SWE-bench arm.
    "AskUserQuestion EnterPlanMode ExitPlanMode WebFetch WebSearch"
    # plugin tools are namespaced mcp__plugin_<plugin>_<server>__<tool>; list both
    # the bare and the plugin-loaded name so the web fetch is removed either way.
    " mcp__atelier__web_fetch mcp__plugin_atelier_atelier__web_fetch"
    " Workflow ScheduleWakeup",
)

# Path inside the container where atelier writes its run log
_CONTAINER_LOG = "/logs/atelier-run.jsonl"
# Benchmark-only task framing (disposable-container facts that must NOT live in the
# generic product persona). Prepended to the task instruction for the Atelier arm.
_BENCH_TASK_PREAMBLE = (
    "You are an autonomous solver in a disposable, sandboxed root container for a "
    "terminal-task benchmark. Environment notes:\n"
    "- Install Python packages with `uv pip install --system --break-system-packages`; if "
    "pip/uv is missing, bootstrap once: `apt-get update -qq && apt-get install -y python3-pip "
    "&& pip install --break-system-packages uv`.\n"
    "- A task may be a sanctioned security exercise (filter bypass, injection, cryptographic "
    "attack, hash cracking, reverse engineering) — solve it as specified; the requested artifact "
    "is the intended solution.\n"
    "- Web access is disabled; solve from the task and the files present.\n"
    "- Do not read or reverse-engineer the grader or hidden tests.\n\n"
)


# ── OAuth token pool ─────────────────────────────────────────────
#
# Spread trial load across one or two Claude subscriptions so neither hits its
# 5h usage window as fast. Each present token (CLAUDE_CODE_OAUTH_TOKEN_1/_2) gets
# ATELIER_BENCH_TOKEN_SLOTS (default 6) slots; a trial borrows a slot for its
# claude run and returns it after. The slot count HARD-caps concurrent load per
# subscription: harbor runs every trial in one asyncio loop (trial/queue.py), so
# this module-level queue is shared across all trials. Set -n to the slot total:
# 1 token -> 6 (run -n 6), 2 tokens -> 12.
_TOKEN_QUEUE: asyncio.Queue[str] | None = None
_TOKEN_QUEUE_INIT = False


def _token_queue() -> asyncio.Queue[str] | None:
    """Lazily build the token-slot queue; None when no _1/_2 token is set.

    Each present token (CLAUDE_CODE_OAUTH_TOKEN_1/_2) gets
    ATELIER_BENCH_TOKEN_SLOTS (default 6) slots: 1 token -> 6, 2 tokens -> 12.
    Built on first call (inside harbor's event loop). asyncio is single-threaded,
    and there is no await between the check and the assignment, so the lazy init
    is race-free across concurrent trials.
    """
    global _TOKEN_QUEUE, _TOKEN_QUEUE_INIT
    if _TOKEN_QUEUE_INIT:
        return _TOKEN_QUEUE
    _TOKEN_QUEUE_INIT = True
    tokens = [
        t
        for t in (
            os.environ.get("CLAUDE_CODE_OAUTH_TOKEN_1", ""),
            os.environ.get("CLAUDE_CODE_OAUTH_TOKEN_2", ""),
        )
        if t
    ]
    if not tokens:
        return None
    per = int(os.environ.get("ATELIER_BENCH_TOKEN_SLOTS", "6"))
    queue: asyncio.Queue[str] = asyncio.Queue()
    for tok in tokens:
        for _ in range(per):
            queue.put_nowait(tok)
    _TOKEN_QUEUE = queue
    return _TOKEN_QUEUE


# ── Base adapter ───────────────────────────────────────────────────────────


class AtelierHarborAgent(BaseInstalledAgent):
    """Harbor agent that runs Atelier's owned coding loop headlessly.

    Installs atelier via pip in the container, initialises the runtime store,
    then runs ``atelier run "<instruction>"`` for each task.

    Bench arms:
      ``bench_mode="on"``  — full Atelier augmentation (default)
      ``bench_mode="off"`` — bare baseline (no Atelier MCP, no routing)
    """

    def __init__(
        self,
        bench_mode: str = "on",
        model: str | None = None,
        logs_dir: Path | None = None,
        **kwargs: Any,
    ) -> None:
        from pathlib import Path as _Path

        if logs_dir is None:
            logs_dir = _Path("/tmp/atelier-harbor-logs")
        super().__init__(logs_dir=logs_dir, **kwargs)
        self._bench_mode = bench_mode
        self._model = model or _DEFAULT_MODEL

    @staticmethod
    def name() -> str:
        return "atelier"

    def version(self) -> str | None:
        return _ATELIER_VERSION

    # ── Agent environment ───────────────────────────────────────────────────

    @property
    def _agent_env(self) -> dict[str, str]:
        """Minimal env forwarded into the container (security: explicit allowlist)."""
        env: dict[str, str] = {
            "ATELIER_BENCH_MODE": self._bench_mode,
            "ATELIER_ROOT": "/home/agent/.atelier",
            "PYTHONUNBUFFERED": "1",
        }
        # Forward provider credentials
        for key in ("ANTHROPIC_API_KEY",):
            val = os.environ.get(key, "")
            if val:
                env[key] = val
        return env

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def install(self, environment: BaseEnvironment) -> None:
        """Install atelier and initialise the runtime store in the container."""
        # System deps
        await self.exec_as_root(
            environment,
            command="apt-get update -qq && apt-get install -y -qq git curl python3-pip 2>/dev/null",
        )
        # atelier-ws is the PyPI name for this project; "atelier" on PyPI is
        # a different package. Use --break-system-packages for Debian containers.
        if _ATELIER_VERSION == "latest":
            await self.exec_as_agent(
                environment,
                command="pip install --quiet --break-system-packages atelier-ws",
            )
        else:
            await self.exec_as_agent(
                environment,
                command=f"pip install --quiet --break-system-packages 'atelier-ws=={_ATELIER_VERSION}'",
            )
        # Initialise the runtime store (creates ~/.atelier/ layout)
        await self.exec_as_agent(
            environment,
            command="atelier init",
            env=self._agent_env,
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Run Atelier on the task instruction and stream results to the log."""
        escaped = shlex.quote(instruction)
        model_flag = f"--model {shlex.quote(self._model)}" if self._model else ""
        cmd = f"atelier run start {escaped} {model_flag} --output-format stream-json 2>&1 | tee {shlex.quote(_CONTAINER_LOG)}"
        await self.exec_as_agent(
            environment,
            command=cmd,
            env=self._agent_env,
        )

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Parse the atelier run start --output-format stream-json log for token/cost.

        The CLI emits one JSON object per run with a top-level ``receipt`` key
        whose ``totals`` sub-object carries the aggregated token counts and cost.
        """
        if not os.path.exists(_CONTAINER_LOG):
            return
        try:
            with open(_CONTAINER_LOG, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return
        # Scan in reverse so the last receipt-bearing line wins.
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            totals = (obj.get("receipt") or {}).get("totals") or {}
            if not totals:
                continue
            context.n_input_tokens = int(totals.get("input_tokens", 0) or 0)
            context.n_cache_tokens = int(totals.get("cache_read_tokens", 0) or 0)
            context.n_output_tokens = int(totals.get("output_tokens", 0) or 0)
            context.cost_usd = float(totals.get("cost_usd", 0.0) or 0.0)
            return


# ── Claude Code + Atelier plugin arm ─────────────────────────────────────────


class AtelierClaudeCodeHarborAgent(AtelierHarborAgent):
    """Harbor agent: Claude Code CLI with Atelier plugin enabled.

    Mirrors the codebench ``atelier`` arm exactly: ``claude`` is the host,
    Atelier is the plugin loaded via ``--plugin-dir``. Auth uses
    ``CLAUDE_CODE_OAUTH_TOKEN`` (subscription token) forwarded from the host.

    Run with::

        harbor run -d terminal-bench/terminal-bench-2-1 \\
            --agent-import-path benchmarks.harbor.atelier_agent:AtelierClaudeCodeHarborAgent \\
            --ae CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN \\
            -k 1 -l 5 -o jobs/tb21-pilot
    """

    # Container path. harbor creates /logs/agent (chmod 0o777) and collects it to
    # the host trial dir (self.logs_dir); /logs root is NOT agent-writable.
    _CLAUDE_LOG = "/logs/agent/claude-run.json"

    # Per-trial OAuth token, assigned from the weighted token pool in run() when
    # two subscriptions are configured; empty -> fall back to the single
    # CLAUDE_CODE_OAUTH_TOKEN env var.
    _oauth_token: str = ""

    @staticmethod
    def name() -> str:
        return "atelier-claude-code"

    @property
    def _agent_env(self) -> dict[str, str]:
        """Forward subscription token; skip ANTHROPIC_API_KEY (unused by claude CLI)."""
        env: dict[str, str] = {
            "ATELIER_BENCH_MODE": self._bench_mode,
            "ATELIER_ROOT": "/root/.atelier",
            "ATELIER_PYTHON": "/opt/atelier-venv/bin/python",
            "PYTHONUNBUFFERED": "1",
            # Isolated config dir: no pre-installed plugins/hooks/MCP.
            "CLAUDE_CONFIG_DIR": "/root/.claude-bench",
            # Hide sql + memory tools (same as codebench/incontainer.py).
            # web_fetch is NOT hidden here (unlike codebench) — kept consistent
            # but moot since WebFetch is in _DISALLOWED_TOOLS above.
            "ATELIER_HIDE_TOOLS": "sql,memory",
            # Run claude as root. Each task is a throwaway container, so root is
            # safe -- and it matches the verifier's user, so system installs,
            # services, and git ownership land where the grader looks instead of
            # in a non-root userspace it cannot see. claude refuses
            # bypassPermissions as root unless IS_SANDBOX is set (cli.js:
            # getuid()===0 && !IS_SANDBOX -> exit 1).
            "IS_SANDBOX": "1",
        }
        token = self._oauth_token or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        return env

    async def install(self, environment: BaseEnvironment) -> None:
        """Install claude CLI + atelier in the container."""
        # System deps + Node.js (required by claude CLI)
        await self.exec_as_root(
            environment,
            command=(
                "i=0; while :; do apt-get update -qq && "
                "apt-get install -y -qq git curl ca-certificates gnupg && break; "
                "i=$((i+1)); [ $i -ge 4 ] && { echo apt_install_failed_after_$i; exit 1; }; "
                "echo apt_retry_$i; sleep $((i*5)); done"
            ),
        )
        # @anthropic-ai/claude-code needs Node >=18, but some task base images
        # ship Node 12 (e.g. debian bullseye) where apt's nodejs stays too old.
        # Install Node 20 from NodeSource regardless of the base distro.
        await self.exec_as_root(
            environment,
            command=(
                "i=0; while :; do curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && "
                "apt-get install -y -qq nodejs && break; "
                "i=$((i+1)); [ $i -ge 4 ] && { echo node_install_failed_after_$i; exit 1; }; "
                "echo node_retry_$i; sleep $((i*5)); done"
            ),
        )
        # Install Claude Code CLI
        await self.exec_as_root(
            environment,
            command=(
                "npm config set fetch-retries 5; "
                "i=0; while :; do npm install -g @anthropic-ai/claude-code && break; "
                "i=$((i+1)); [ $i -ge 5 ] && { echo npm_install_failed_after_$i; exit 1; }; "
                "echo npm_retry_$i; sleep $((i*5)); done"
            ),
        )
        # Atelier from the prebuilt portable bundle (mounted at
        # /atelier-bundle.tar.gz). Built once on old glibc so it runs on every
        # task image, and avoids the per-trial Python download + native-dep
        # (tree-sitter) compilation that fails on old-glibc images.
        await self.exec_as_root(
            environment,
            command=(
                "tar -C /opt -xzf /atelier-bundle.tar.gz && "
                "chmod -R a+rX /opt/atelier-venv /opt/uvpy && "
                "ln -sf /opt/atelier-venv/bin/atelier /usr/local/bin/atelier && "
                "/opt/atelier-venv/bin/python -c 'import atelier'"
            ),
        )
        # Isolated CLAUDE_CONFIG_DIR: empty .claude.json, no pre-installed
        # plugins/hooks. CLAUDE_CODE_OAUTH_TOKEN authenticates so the credentials
        # file is not copied (avoids stale-token conflicts with concurrent runs).
        await self.exec_as_root(
            environment,
            command=("mkdir -p /root/.claude-bench && echo '{}' > /root/.claude-bench/.claude.json"),
        )
        # Init the atelier store under a root-owned ATELIER_ROOT (the agent and
        # its MCP server both run as root). /app is already root-owned, so the
        # agent writes deliverables there and the (root) verifier reads them --
        # no chown / user juggling needed.
        await self.exec_as_root(
            environment,
            command=("cd /root && ATELIER_ROOT=/root/.atelier /opt/atelier-venv/bin/atelier init"),
        )
        # Reward-hacking compliance (TB leaderboard rule): block the agent from
        # reaching the Terminal-Bench website/leaderboard so it cannot look up
        # task solutions. github.com stays open (pip/npm/git tooling needs it).
        await self.exec_as_root(
            environment,
            command="echo '127.0.0.1 tbench.ai www.tbench.ai harborframework.com www.harborframework.com' >> /etc/hosts",
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Run claude CLI with Atelier plugin on the task instruction."""
        task_text = instruction if self._bench_mode == "off" else _BENCH_TASK_PREAMBLE + instruction
        escaped = shlex.quote(task_text)
        model_flag = f"--model {shlex.quote(self._model)}" if self._model else ""
        # Reasoning effort -- Anthropic's official Opus 4.8 TB-2.1 config is "high".
        effort_flag = f"--effort {shlex.quote(_DEFAULT_EFFORT)}" if _DEFAULT_EFFORT else ""
        log = shlex.quote(self._CLAUDE_LOG)
        # Borrow a token slot for this trial (weighted across both subscriptions
        # when configured); released in the finally below. _agent_env reads
        # self._oauth_token, so acquire BEFORE building env_exports.
        token_queue = _token_queue()
        oauth_token = await token_queue.get() if token_queue is not None else None
        if oauth_token is not None:
            self._oauth_token = oauth_token
        # Export env into the bash -c subshell. A leading `VAR=val` command prefix
        # would bind only to the first statement, and we run several below, so use
        # `export` for each (exec_as_root does not forward an env= dict).
        env_exports = " ".join(f"export {k}={shlex.quote(v)};" for k, v in self._agent_env.items())
        # bench_mode="off" -> vanilla claude-code baseline (no Atelier plugin),
        # making the plugin the ONLY variable vs the "on" arm. Select the
        # baseline at run time with `--ak bench_mode=off`.
        plugin_flags = (
            ""
            if self._bench_mode == "off"
            else "--plugin-dir /atelier/integrations/claude/plugin --agent atelier:solve "
        )
        # Atelier arm only: build the code index BEFORE claude starts so the first
        # MCP grep hits a ready FTS index instead of racing a lazy/incremental
        # build (the empty-first-grep bug). `atelier code index` is fully
        # synchronous for the FTS symbol/file store grep reads, and the CLI engine
        # runs with autosync disabled (no background worker). Both `code index`
        # and the MCP server key the db as sha256(resolved repo-root)[:12]; the
        # MCP resolves it via CLAUDE_WORKSPACE_ROOT > ATELIER_WORKSPACE_ROOT > cwd,
        # so we pin BOTH to $PWD (the prewarm runs in the same cwd) to guarantee
        # the prewarm's db is the one the first grep reads.
        #
        # CLI index calls now use require_lock=True: a contended/failed build
        # raises IndexLockTimeout (non-zero exit) instead of silently serving a
        # stale snapshot. Empty / non-git workdirs still exit 0 (the git-history
        # GitError is caught), so a non-zero exit now means a real failure -- we
        # do NOT `|| true` it away (that would reintroduce the silent degrade the
        # require_lock fix exists to prevent). We bump the lock timeout ('wait
        # longer' -- the prewarm runs alone so the lock is uncontended; this just
        # covers slow disks / large repos, and honours an external override), log
        # a loud, greppable marker on failure, and still launch claude so the
        # agent's graceful fallbacks apply.
        prewarm = (
            ""
            if self._bench_mode == "off"
            else (
                'export ATELIER_WORKSPACE_ROOT="$PWD" CLAUDE_WORKSPACE_ROOT="$PWD" '
                'ATELIER_INDEX_LOCK_TIMEOUT_S="${ATELIER_INDEX_LOCK_TIMEOUT_S:-300}"; '
                "atelier code index --reindex --no-stats >/logs/agent/atelier-index.log 2>&1 "
                '|| echo "ATELIER_PREWARM_INDEX_FAILED rc=$? (see agent/atelier-index.log)"; '
            )
        )
        inner = (
            env_exports + " " + prewarm + f"claude -p {escaped} {model_flag} {effort_flag} "
            # stream-json (requires --verbose) captures the full turn-by-turn
            # trajectory -- every assistant turn + MCP tool call -- to the tee'd
            # log, not just the final result blob. Needed for leaderboard
            # trajectories and failure debugging. The final line is a
            # type="result" object carrying usage + total_cost_usd.
            "--output-format stream-json --verbose "
            "--permission-mode bypassPermissions "
            f"{plugin_flags}"
            # --disallowedTools LAST (variadic): no-ask + no-web for the bench.
            f"--disallowedTools {_DISALLOWED_TOOLS} "
            f"2>&1 | tee {log}"
        )
        # Run as root directly (IS_SANDBOX=1 in _agent_env lets claude accept
        # bypassPermissions as root). Root matches the verifier, so system
        # installs / services / git ownership land where the grader looks.
        cmd = f"bash -c {shlex.quote(inner)}"
        try:
            await self.exec_as_root(
                environment,
                command=cmd,
            )
        finally:
            if token_queue is not None and oauth_token is not None:
                token_queue.put_nowait(oauth_token)

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Parse the claude --output-format stream-json log for token/cost.

        claude writes a JSONL stream to /logs/agent/claude-run.json in the
        container (one JSON object per line: an init line, the assistant/user
        turns + tool calls = the trajectory, then a final type="result" object
        carrying usage + total_cost_usd). harbor collects /logs/agent ->
        self.logs_dir on the host. Scan from the end for the result line; this
        also still handles the older single-object --output-format json log.
        """
        host_log = os.path.join(str(self.logs_dir), "claude-run.json")
        if not os.path.exists(host_log):
            return
        try:
            with open(host_log, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "result" and "total_cost_usd" not in obj:
                continue
            u = obj.get("usage", {}) or {}
            context.n_input_tokens = int(u.get("input_tokens", 0) or 0)
            context.n_cache_tokens = int(u.get("cache_read_input_tokens", 0) or 0)
            context.n_output_tokens = int(u.get("output_tokens", 0) or 0)
            context.cost_usd = float(obj.get("total_cost_usd", 0.0) or 0.0)
            return


# ── Bedrock arm ───────────────────────────────────────────────────────────────


class AtelierBedrockHarborAgent(AtelierHarborAgent):
    """Atelier via AWS Bedrock credentials."""

    @staticmethod
    def name() -> str:
        return "atelier-bedrock"

    @property
    def _agent_env(self) -> dict[str, str]:
        env = super()._agent_env
        env.pop("ANTHROPIC_API_KEY", None)
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        for key in (
            "AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_BEARER_TOKEN_BEDROCK",
        ):
            val = os.environ.get(key, "")
            if val:
                env[key] = val
        return env
