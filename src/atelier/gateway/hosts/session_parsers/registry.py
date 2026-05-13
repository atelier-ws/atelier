"""Shared host registry for session import, reconstruction, and analysis paths."""

from __future__ import annotations

from importlib import import_module
from typing import Any

SUPPORTED_SESSION_IMPORT_HOSTS: tuple[str, ...] = (
    "antigravity",
    "claude",
    "codex",
    "copilot",
    "crush",
    "cursor",
    "cursor-agent",
    "droid",
    "gemini",
    "goose",
    "kilo-code",
    "kiro",
    "omp",
    "openclaw",
    "opencode",
    "pi",
    "qwen",
    "roo-code",
)

HOST_IMPORTER_CLASSES: dict[str, tuple[str, str]] = {
    "antigravity": ("atelier.gateway.hosts.session_parsers.antigravity", "AntigravityImporter"),
    "claude": ("atelier.gateway.hosts.session_parsers.claude", "ClaudeImporter"),
    "codex": ("atelier.gateway.hosts.session_parsers.codex", "CodexImporter"),
    "copilot": ("atelier.gateway.hosts.session_parsers.copilot", "CopilotImporter"),
    "crush": ("atelier.gateway.hosts.session_parsers.crush", "CrushImporter"),
    "cursor": ("atelier.gateway.hosts.session_parsers.cursor", "CursorImporter"),
    "cursor-agent": ("atelier.gateway.hosts.session_parsers.cursor_agent", "CursorAgentImporter"),
    "droid": ("atelier.gateway.hosts.session_parsers.droid", "DroidImporter"),
    "gemini": ("atelier.gateway.hosts.session_parsers.gemini", "GeminiImporter"),
    "goose": ("atelier.gateway.hosts.session_parsers.goose", "GooseImporter"),
    "kilo-code": ("atelier.gateway.hosts.session_parsers.kilo_code", "KiloCodeImporter"),
    "kiro": ("atelier.gateway.hosts.session_parsers.kiro", "KiroImporter"),
    "omp": ("atelier.gateway.hosts.session_parsers.pi", "OmpImporter"),
    "openclaw": ("atelier.gateway.hosts.session_parsers.openclaw", "OpenClawImporter"),
    "opencode": ("atelier.gateway.hosts.session_parsers.opencode", "OpenCodeImporter"),
    "pi": ("atelier.gateway.hosts.session_parsers.pi", "PiImporter"),
    "qwen": ("atelier.gateway.hosts.session_parsers.qwen", "QwenImporter"),
    "roo-code": ("atelier.gateway.hosts.session_parsers.roo_code", "RooCodeImporter"),
}


def iter_importer_classes() -> list[tuple[str, type[Any]]]:
    """Resolve importer classes lazily so callers do not import every host eagerly."""

    resolved: list[tuple[str, type[Any]]] = []
    for host in SUPPORTED_SESSION_IMPORT_HOSTS:
        module_name, class_name = HOST_IMPORTER_CLASSES[host]
        module = import_module(module_name)
        resolved.append((host, getattr(module, class_name)))
    return resolved
