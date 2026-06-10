from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from atelier.core.foundation.paths import DEFAULT_STORE_DIRNAME, default_store_root

RUNTIME_ROLE_IDS = ("code", "general", "explore", "plan", "execute", "review", "research", "solve")
HOST_ROLE_IDS = ("code", "explore", "plan", "execute", "research", "review", "solve")
HOST_IDS = ("default", "copilot", "claude", "codex", "opencode", "antigravity", "cursor", "hermes")

CANONICAL_COPILOT_AGENT_MODEL = "gpt-5.4"
TOP_MODEL_CHOICES = (
    "claude-opus-4.8",
    "claude-sonnet-4.6",
    "gpt-5.5",
    "gpt-5.4",
)

DEFAULT_RUNTIME_MODELS = {
    "code": "claude-opus-4.8",
    "general": "claude-opus-4.8",
    "explore": "claude-sonnet-4.6",
    "plan": "claude-sonnet-4.6",
    "execute": "claude-opus-4.8",
    "review": "claude-sonnet-4.6",
    "research": "claude-sonnet-4.6",
    "solve": "claude-opus-4.8",
}

_CLAUDE_DOT_VERSION_RE = re.compile(r"(\d)\.(?=\d)")


def global_model_settings_path() -> Path:
    return default_store_root() / "settings.json"


def workspace_model_settings_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().resolve() / DEFAULT_STORE_DIRNAME / "settings.json"


def load_model_settings(workspace_root: str | Path | None = None) -> dict[str, Any]:
    settings = _normalized_settings(_read_json(global_model_settings_path()))
    if workspace_root is None:
        return settings
    local_path = workspace_model_settings_path(workspace_root)
    local = _normalized_settings(_read_json(local_path))
    return _deep_merge(settings, local)


def write_workspace_model_settings(workspace_root: str | Path, payload: dict[str, Any]) -> Path:
    path = workspace_model_settings_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def normalize_model_for_host(host: str, model: str | None) -> str | None:
    candidate = str(model or "").strip()
    if not candidate:
        return None
    if host == "claude" and candidate.startswith("claude-"):
        return _CLAUDE_DOT_VERSION_RE.sub(r"\1-", candidate)
    if host == "opencode" and "/" not in candidate:
        if candidate.startswith("claude-"):
            return "anthropic/" + _CLAUDE_DOT_VERSION_RE.sub(r"\1-", candidate)
        if candidate.startswith("gpt-"):
            return "openai/" + candidate
    return candidate


def resolve_runtime_model(role_id: str, workspace_root: str | Path | None = None) -> str:
    default = DEFAULT_RUNTIME_MODELS.get(role_id)
    if default is None:
        raise KeyError(f"unknown runtime role: {role_id}")
    settings = load_model_settings(workspace_root)
    raw = settings.get("models", {}).get("runtime", {}).get("roles", {}).get(role_id)
    candidate = str(raw or "").strip()
    return default if not candidate or candidate == "auto" else candidate


def resolve_host_model(
    host: str,
    role_id: str,
    *,
    workspace_root: str | Path | None = None,
    fallback: str | None = None,
) -> str | None:
    settings = load_model_settings(workspace_root)
    hosts = settings.get("models", {}).get("hosts", {})
    for host_key in (host, "default"):
        host_settings = hosts.get(host_key, {})
        roles = host_settings.get("roles", {})
        if not isinstance(roles, dict):
            continue
        if _is_legacy_auto_host_stub(roles):
            continue
        for key in (role_id, "*"):
            raw = roles.get(key)
            candidate = str(raw or "").strip()
            if candidate:
                return None if candidate == "auto" else candidate
    try:
        return resolve_runtime_model(role_id, workspace_root)
    except KeyError:
        return fallback


def build_runtime_settings_payload(models: dict[str, str]) -> dict[str, Any]:
    return {"models": {"runtime": {"roles": dict(models)}}}


def set_host_role_models(
    payload: dict[str, Any],
    *,
    host: str,
    models: dict[str, str],
) -> dict[str, Any]:
    updated = _deep_merge({}, payload)
    model_root = updated.setdefault("models", {})
    hosts = model_root.setdefault("hosts", {})
    host_entry = hosts.setdefault(host, {})
    host_entry["roles"] = dict(models)
    return updated


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalized_settings(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    models = data.get("models")
    if not isinstance(models, dict):
        return {}
    runtime = models.get("runtime")
    hosts = models.get("hosts")
    normalized: dict[str, Any] = {"models": {}}
    if isinstance(runtime, dict):
        normalized["models"]["runtime"] = {"roles": _normalized_role_map(runtime.get("roles"), allow_auto=False)}
    if isinstance(hosts, dict):
        normalized_hosts: dict[str, Any] = {}
        for host_key, host_value in hosts.items():
            if str(host_key) not in HOST_IDS:
                continue
            if not isinstance(host_value, dict):
                continue
            normalized_hosts[str(host_key)] = {
                "roles": _normalized_role_map(host_value.get("roles"), allow_auto=True),
            }
        normalized["models"]["hosts"] = normalized_hosts
    return normalized


def _normalized_role_map(raw: Any, *, allow_auto: bool) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    allowed_keys = set(RUNTIME_ROLE_IDS if not allow_auto else HOST_ROLE_IDS) | {"*"}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        role_id = str(key).strip()
        if role_id not in allowed_keys:
            continue
        candidate = str(value or "").strip()
        if not candidate:
            continue
        if candidate == "auto" and not allow_auto:
            continue
        normalized[role_id] = candidate
    return normalized


def _is_legacy_auto_host_stub(roles: dict[str, Any]) -> bool:
    role_keys = {str(key).strip() for key in roles}
    if role_keys != set(HOST_ROLE_IDS):
        return False
    return all(str(roles.get(role_id) or "").strip() == "auto" for role_id in HOST_ROLE_IDS)


def _deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


__all__ = [
    "CANONICAL_COPILOT_AGENT_MODEL",
    "DEFAULT_RUNTIME_MODELS",
    "HOST_IDS",
    "HOST_ROLE_IDS",
    "RUNTIME_ROLE_IDS",
    "TOP_MODEL_CHOICES",
    "build_runtime_settings_payload",
    "global_model_settings_path",
    "load_model_settings",
    "normalize_model_for_host",
    "resolve_host_model",
    "resolve_runtime_model",
    "set_host_role_models",
    "workspace_model_settings_path",
    "write_workspace_model_settings",
]
