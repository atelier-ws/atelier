"""Central runtime visibility policy.

This module owns the always-on public tool/skill surface for Atelier runtime
code. Keep hardcoded hidden lists here so MCP, HTTP, CLI, and UI-facing
metadata stay consistent without a separate dev-mode branch.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

MEMORY_BACKEND_ENV_VAR = "ATELIER_MEMORY_BACKEND"
TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
MEMORY_BACKENDS = frozenset({"sqlite", "letta", "openmemory"})

HIDDEN_LLM_TOOLS = frozenset(
    {
        "rescue",
        "verify",
        "trace",
        "workflow",
        "agent",
        "compact",
        "context",
        # WS4 graph analytics (blast radius / dead code / cycles / coupling /
        # symbol centrality): registered and callable by name, but kept off the
        # advertised surface to preserve the lean public tool set.
        "graph",
        # WS8 G11 security scan (SAST first iteration): callable by name but kept
        # off the advertised surface to preserve the lean public tool set.
        "scan",
        # WS12 N8 on-demand tool-usage playbook: callable by name so the
        # orientation guidance lives in one fetch, but kept off the advertised
        # surface to preserve the lean public tool set.
        "orient",
        # Repo/admin code-intel ops: callable by name (tests, CLI, power use)
        # but not surfaced to agents.
        "index",
        "blame",
        "rename",
        "cache_status",
        "cache_invalidate",
    }
)
HIDDEN_SKILLS = frozenset(
    {
        "analyze-failures",
        "context",
        "evals",
        "rescue",
        "savings",
        "status",
        "record",
    }
)


def bool_env(name: str, default: bool = False, env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    raw = values.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in TRUE_ENV_VALUES


def mcp_tool_description(tool_name: str, description: str | None) -> str:
    return str(description or "")


def mcp_tool_visible_to_llm(tool_name: str) -> bool:
    # Bench-off overrides the normal public surface — the baseline arm must not
    # see Atelier MCP tools. Imported lazily so reading runtime config does not
    # couple core to the optional bench package at module load time.
    from atelier.bench.mode import is_off as _bench_is_off

    if _bench_is_off():
        return False
    return tool_name not in HIDDEN_LLM_TOOLS


def mcp_tool_mode(tool_name: str) -> str:
    return "hidden" if tool_name in HIDDEN_LLM_TOOLS else "active"


def skill_visible(skill_name: str) -> bool:
    return skill_name not in HIDDEN_SKILLS


def resolve_install_profile(env: Mapping[str, str] | None = None) -> str:
    return "stable"


def install_profile_warning(profile: str | None = None, env: Mapping[str, str] | None = None) -> str | None:
    return None


def resolve_memory_backend(
    *,
    root: str | Path | None = None,
    prefer: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if env is None else env

    env_backend = values.get(MEMORY_BACKEND_ENV_VAR, "").strip().lower()
    if env_backend:
        return _validated_memory_backend(env_backend)

    if root is not None and tomllib is not None:
        config_path = Path(root) / "config.toml"
        if config_path.exists():
            try:
                data = tomllib.loads(config_path.read_text(encoding="utf-8"))
                memory = data.get("memory", {}) if isinstance(data, dict) else {}
                config_backend = str(memory.get("backend", "")).strip().lower()
                if config_backend:
                    return _validated_memory_backend(config_backend)
            except (tomllib.TOMLDecodeError, OSError, ValueError):
                # Keep runtime robust; invalid config falls back to defaults.
                logger.warning("Invalid config.toml; falling back to defaults", exc_info=True)

    fallback = (prefer or "sqlite").strip().lower()
    return _validated_memory_backend(fallback)


def _validated_memory_backend(value: str) -> str:
    if value not in MEMORY_BACKENDS:
        allowed = ", ".join(sorted(MEMORY_BACKENDS))
        raise ValueError(f"memory backend must be one of: {allowed}")
    return value
