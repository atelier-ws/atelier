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

# Path inside the container where atelier writes its run log
_CONTAINER_LOG = "/logs/atelier-run.jsonl"


# ── Base adapter ──────────────────────────────────────────────────────────────


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

    _CLAUDE_LOG = "/logs/claude-run.json"

    @staticmethod
    def name() -> str:
        return "atelier-claude-code"

    @property
    def _agent_env(self) -> dict[str, str]:
        """Forward subscription token; skip ANTHROPIC_API_KEY (unused by claude CLI)."""
        env: dict[str, str] = {
            "ATELIER_BENCH_MODE": self._bench_mode,
            "ATELIER_ROOT": "/home/agent/.atelier",
            "PYTHONUNBUFFERED": "1",
            # Isolated config dir: no pre-installed plugins/hooks/MCP.
            "CLAUDE_CONFIG_DIR": "/home/bench/.claude-bench",
        }
        for key in ("CLAUDE_CODE_OAUTH_TOKEN",):
            val = os.environ.get(key, "")
            if val:
                env[key] = val
        return env

    async def install(self, environment: BaseEnvironment) -> None:
        """Install claude CLI + atelier in the container."""
        # System deps + Node.js (required by claude CLI)
        await self.exec_as_root(
            environment,
            command=("apt-get update -qq && apt-get install -y -qq git curl python3-pip nodejs npm 2>/dev/null"),
        )
        # Install Claude Code CLI
        await self.exec_as_root(
            environment,
            command="npm install -g @anthropic-ai/claude-code 2>/dev/null",
        )
        # Install atelier from the repo mounted at /atelier (not on PyPI).
        # ATELIER_SKIP_MYPYC=1 skips the mypyc compilation step that runs
        # via hatch_build.py — not needed inside the bench container.
        await self.exec_as_root(
            environment,
            command="ATELIER_SKIP_MYPYC=1 pip install --quiet --break-system-packages /atelier",
        )
        # Initialise atelier runtime store (the MCP server needs it).
        # Use python3 -m so we don't depend on the binary being on PATH.
        await self.exec_as_agent(
            environment,
            command="python3 -m atelier.gateway.cli init",
            env=self._agent_env,
        )
        # Create a non-root user for running claude (it refuses --permission-mode
        # bypassPermissions when running as root).
        await self.exec_as_root(
            environment,
            command="useradd -m -s /bin/bash bench 2>/dev/null || true",
        )
        # Isolated CLAUDE_CONFIG_DIR: empty .claude.json, no pre-installed
        # plugins/hooks. CLAUDE_CODE_OAUTH_TOKEN authenticates so credentials
        # file is not copied (avoids stale-token conflicts with concurrent runs).
        await self.exec_as_root(
            environment,
            command=(
                "mkdir -p /home/bench/.claude-bench && "
                "echo '{}' > /home/bench/.claude-bench/.claude.json && "
                "chown -R bench:bench /home/bench/.claude-bench"
            ),
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Run claude CLI with Atelier plugin on the task instruction."""
        escaped = shlex.quote(instruction)
        model_flag = f"--model {shlex.quote(self._model)}" if self._model else ""
        log = shlex.quote(self._CLAUDE_LOG)
        # Build env exports for the su subshell (env= dict is not forwarded by su -c)
        env_exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in self._agent_env.items())
        inner = (
            f"claude -p {escaped} {model_flag} "
            "--output-format json "
            "--permission-mode bypassPermissions "
            "--plugin-dir /atelier/integrations/claude/plugin "
            "--agent atelier:code "
            f"2>&1 | tee {log}"
        )
        # claude refuses --permission-mode bypassPermissions when run as root.
        # runuser (util-linux) switches user without requiring a password, unlike su.
        cmd = f"runuser -u bench -- bash -c {shlex.quote(env_exports + ' ' + inner)}"
        await self.exec_as_root(
            environment,
            command=cmd,
        )

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Parse claude --output-format json output for token/cost accounting."""
        if not os.path.exists(self._CLAUDE_LOG):
            return
        try:
            with open(self._CLAUDE_LOG, encoding="utf-8") as fh:
                text = fh.read().strip()
            if not text:
                return
            obj = json.loads(text)
        except (OSError, json.JSONDecodeError):
            return
        u = obj.get("usage", {}) or {}
        context.n_input_tokens = int(u.get("input_tokens", 0) or 0)
        context.n_cache_tokens = int(u.get("cache_read_input_tokens", 0) or 0)
        context.n_output_tokens = int(u.get("output_tokens", 0) or 0)
        context.cost_usd = float(obj.get("total_cost_usd", 0.0) or 0.0)


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
