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
        # Install atelier (editable from repo or from PyPI)
        if _ATELIER_VERSION == "latest":
            await self.exec_as_agent(
                environment,
                command="pip install --quiet atelier || pip install --quiet atelier-ws",
            )
        else:
            await self.exec_as_agent(
                environment,
                command=f"pip install --quiet 'atelier=={_ATELIER_VERSION}'",
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
        cmd = f"atelier run {escaped} {model_flag} --format stream-json " f"2>&1 | tee {shlex.quote(_CONTAINER_LOG)}"
        await self.exec_as_agent(
            environment,
            command=cmd,
            env=self._agent_env,
        )

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Parse the atelier stream-json log for token/cost accounting."""
        log_path = _CONTAINER_LOG
        if not os.path.exists(log_path):
            return
        input_tokens = 0
        output_tokens = 0
        cache_tokens = 0
        cost_usd = 0.0
        try:
            with open(log_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "usage":
                        input_tokens += obj.get("input_tokens", 0)
                        output_tokens += obj.get("output_tokens", 0)
                        cache_tokens += obj.get("cache_read_input_tokens", 0)
                        cost_usd += obj.get("cost_usd", 0.0)
        except OSError:
            pass
        context.n_input_tokens = input_tokens + cache_tokens
        context.n_cache_tokens = cache_tokens
        context.n_output_tokens = output_tokens
        context.cost_usd = cost_usd


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
