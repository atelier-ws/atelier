from __future__ import annotations

import json
import shutil
from pathlib import Path

from atelier.core.capabilities.default_definitions import (
    SURFACED_ROLE_IDS,
    build_default_registry,
    load_mode_docs,
)
from atelier.core.capabilities.model_settings import (
    CANONICAL_COPILOT_AGENT_MODEL,
    load_model_settings,
    normalize_model_for_host,
    resolve_host_model,
)

ATELIER_REPO_ROOT = Path(__file__).resolve().parents[4]


def workspace_copilot_agent_text(
    role_id: str,
    workspace_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> str:
    root = _resolve_repo_root(repo_root)
    text = (root / "integrations" / "copilot" / "agents" / _copilot_agent_filename(role_id)).read_text(encoding="utf-8")
    model = resolve_host_model(
        "copilot",
        role_id,
        workspace_root=workspace_root,
        fallback=CANONICAL_COPILOT_AGENT_MODEL,
    )
    return rewrite_agent_model(text, model)


def workspace_claude_agent_text(
    role_id: str,
    workspace_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> str:
    root = _resolve_repo_root(repo_root)
    text = (root / "integrations" / "claude" / "plugin" / "agents" / f"{role_id}.md").read_text(encoding="utf-8")
    # Only inject model if user explicitly set a host override (otherwise inherit session model)
    model = _claude_explicit_host_model(role_id, workspace_root)
    return rewrite_agent_name(rewrite_agent_model(text, model), f"atelier:{role_id}")


def write_workspace_copilot_agents(
    workspace_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> list[Path]:
    workspace = Path(workspace_root).expanduser().resolve()
    target_dir = workspace / ".github" / "agents"
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for stale_name in ["atelier.agent.md", *(f"atelier.{role_id}.agent.md" for role_id in SURFACED_ROLE_IDS)]:
        stale_path = target_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    for role_id in SURFACED_ROLE_IDS:
        target = target_dir / _copilot_agent_filename(role_id)
        target.write_text(workspace_copilot_agent_text(role_id, workspace, repo_root=repo_root), encoding="utf-8")
        written.append(target)

    written.append(_write_copilot_vscode_settings(workspace))
    return written


def write_workspace_claude_overrides(
    workspace_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> list[Path]:
    workspace = Path(workspace_root).expanduser().resolve()
    root = _resolve_repo_root(repo_root)
    written: list[Path] = []

    source_agents = root / "integrations" / "claude" / "plugin" / "agents"
    target_agents = workspace / ".claude" / "agents"
    target_agents.mkdir(parents=True, exist_ok=True)
    for stale_name in (
        [f"{role_id}.md" for role_id in SURFACED_ROLE_IDS]
        + [f"atelier:{role_id}.md" for role_id in SURFACED_ROLE_IDS]
        + [f"atelier.{role_id}.md" for role_id in SURFACED_ROLE_IDS]
    ):
        stale_path = target_agents / stale_name
        if stale_path.exists():
            stale_path.unlink()
    for source in sorted(source_agents.glob("*.md")):
        target = target_agents / f"atelier.{source.stem}.md"
        target.write_text(
            workspace_claude_agent_text(source.stem, workspace, repo_root=root),
            encoding="utf-8",
        )
        written.append(target)

    source_skills = root / "integrations" / "claude" / "plugin" / "skills"
    target_skills = workspace / ".claude" / "skills"
    if target_skills.exists():
        shutil.rmtree(target_skills)
    for source in sorted(source_skills.glob("*/SKILL.md")):
        relative = source.relative_to(source_skills)
        target = target_skills / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(target)

    settings_local = workspace / ".claude" / "settings.local.json"
    current = _read_json(settings_local)
    raw_env = current.get("env")
    env = raw_env if isinstance(raw_env, dict) else {}
    current["env"] = env
    env["CLAUDE_WORKSPACE_ROOT"] = str(workspace)
    current["agent"] = "atelier:code"
    settings_local.parent.mkdir(parents=True, exist_ok=True)
    settings_local.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(settings_local)
    return written


def write_workspace_opencode_agents(
    workspace_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> list[Path]:
    workspace = Path(workspace_root).expanduser().resolve()
    root = _resolve_repo_root(repo_root)
    target_dir = workspace / ".opencode" / "agents"
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for stale_name in ["atelier.md", *(f"{role_id}.md" for role_id in SURFACED_ROLE_IDS if role_id != "code")] + [
        f"atelier.{role_id}.md" for role_id in SURFACED_ROLE_IDS
    ]:
        stale_path = target_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    source_dir = root / "integrations" / "opencode" / "agents"
    for source in sorted(source_dir.glob("*.md")):
        role_id = "code" if source.name == "atelier.md" else source.stem
        target = target_dir / f"atelier.{role_id}.md"
        model = normalize_model_for_host(
            "opencode",
            resolve_host_model("opencode", role_id, workspace_root=workspace, fallback=None),
        )
        target.write_text(rewrite_agent_model(source.read_text(encoding="utf-8"), model), encoding="utf-8")
        written.append(target)
    return written


def write_workspace_cursor_rules(
    workspace_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> list[Path]:
    """Copy generated Cursor role rules (atelier.*.mdc) into the workspace .cursor/rules/ dir."""
    workspace = Path(workspace_root).expanduser().resolve()
    root = _resolve_repo_root(repo_root)
    source_dir = root / "integrations" / "cursor" / "rules"
    target_dir = workspace / ".cursor" / "rules"
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for stale_path in list(target_dir.glob("atelier.*.mdc")):
        stale_path.unlink()

    for source_path in sorted(source_dir.glob("atelier.*.mdc")):
        target = target_dir / source_path.name
        target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(target)
    return written


def write_workspace_codex_agents(
    workspace_root: str | Path,
    *,
    repo_root: str | Path | None = None,
) -> list[Path]:
    workspace = Path(workspace_root).expanduser().resolve()
    root = _resolve_repo_root(repo_root)
    registry = build_default_registry(root)
    mode_docs = load_mode_docs(root)
    target_dir = workspace / ".codex" / "agents"
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for stale_path in target_dir.glob("atelier.*.toml"):
        stale_path.unlink()

    for role_id in SURFACED_ROLE_IDS:
        role = registry.roles[role_id]
        mode_doc = mode_docs[role_id]
        target = target_dir / f"atelier.{role_id}.toml"
        model = normalize_model_for_host(
            "codex",
            resolve_host_model("codex", role_id, workspace_root=workspace, fallback=None),
        )
        target.write_text(
            _render_codex_agent_toml(role_id, role.agent_description, mode_doc.body, model), encoding="utf-8"
        )
        written.append(target)
    return written


def rewrite_agent_model(text: str, model: str | None) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    frontmatter_lines = text[4:end].splitlines()
    body = text[end + len("\n---\n") :]
    has_model_line = any(line.strip().startswith("model:") for line in frontmatter_lines)

    rendered: list[str] = []
    inserted = False
    for raw_line in frontmatter_lines:
        stripped = raw_line.strip()
        if stripped.startswith("model:"):
            if model:
                rendered.append(f"model: {model}")
            continue
        rendered.append(raw_line)
        if model and stripped.startswith("description:") and not inserted and not has_model_line:
            rendered.append(f"model: {model}")
            inserted = True
    if model and not inserted and not has_model_line:
        rendered.append(f"model: {model}")
    return "---\n" + "\n".join(rendered) + "\n---\n" + body


def rewrite_agent_name(text: str, name: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    frontmatter_lines = text[4:end].splitlines()
    body = text[end + len("\n---\n") :]
    has_name_line = any(line.strip().startswith("name:") for line in frontmatter_lines)

    rendered: list[str] = []
    inserted = False
    for raw_line in frontmatter_lines:
        stripped = raw_line.strip()
        if stripped.startswith("name:"):
            rendered.append(f"name: {name}")
            inserted = True
            continue
        rendered.append(raw_line)
    if not inserted and not has_name_line:
        rendered.insert(0, f"name: {name}")
    return "---\n" + "\n".join(rendered) + "\n---\n" + body


def _claude_explicit_host_model(role_id: str, workspace_root: str | Path) -> str | None:
    """Return the model for a Claude agent file, or None to inherit session model.

    Only returns a model string when the user has explicitly set a host override
    for *claude* (or *default* matching this role) in settings.json.  If the value
    is only the runtime default we leave the model line out so Claude uses its
    current session model -- avoids "model not available" warnings for model IDs
    that Claude Code does not recognise.
    """
    workspace = Path(workspace_root).expanduser().resolve()
    settings = load_model_settings(workspace)
    hosts = settings.get("models", {}).get("hosts", {})

    for host_key in ("claude", "default"):
        host_settings = hosts.get(host_key, {})
        roles = host_settings.get("roles", {})
        if not isinstance(roles, dict):
            continue
        for key in (role_id, "*"):
            raw = roles.get(key)
            candidate = str(raw or "").strip()
            if candidate and candidate != "auto":
                return normalize_model_for_host("claude", candidate)
    return None


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_repo_root(repo_root: str | Path | None) -> Path:
    return ATELIER_REPO_ROOT if repo_root is None else Path(repo_root).expanduser().resolve()


def _copilot_agent_filename(role_id: str) -> str:
    return f"atelier.{role_id}.agent.md"


def _write_copilot_vscode_settings(workspace_root: Path) -> Path:
    """Write github.copilot.chat.defaultAgent into .vscode/settings.json.

    Merges with any existing settings so the file is never clobbered.
    """
    target = workspace_root / ".vscode" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    current = _read_json(target)
    current["github.copilot.chat.defaultAgent"] = "atelier.code"
    target.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _render_codex_agent_toml(role_id: str, description: str, instructions: str, model: str | None) -> str:
    body = instructions.strip().replace('"""', '\\"\\"\\"')
    rendered = f'name = "atelier.{role_id}"\n' f'description = "{description}"\n'
    if model:
        rendered += f'model = "{model}"\n'
    rendered += 'developer_instructions = """\n' f"{body}\n" '"""\n'
    return rendered


__all__ = [
    "rewrite_agent_model",
    "rewrite_agent_name",
    "workspace_claude_agent_text",
    "workspace_copilot_agent_text",
    "write_workspace_claude_overrides",
    "write_workspace_codex_agents",
    "write_workspace_copilot_agents",
    "write_workspace_cursor_rules",
    "write_workspace_opencode_agents",
]

# Private module helpers (not exported but discoverable)
