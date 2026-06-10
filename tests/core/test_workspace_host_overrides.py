from __future__ import annotations

import json
from pathlib import Path

from atelier.core.capabilities.workspace_host_overrides import (
    rewrite_agent_model,
    rewrite_agent_name,
    workspace_claude_agent_text,
    workspace_copilot_agent_text,
    write_workspace_claude_overrides,
    write_workspace_codex_agents,
    write_workspace_copilot_agents,
    write_workspace_opencode_agents,
)


def test_rewrite_agent_model_inserts_and_removes_model_line() -> None:
    original = "---\nname: code\ndescription: Main agent\nmaxTurns: 100\n---\n\nBody\n"
    pinned = rewrite_agent_model(original, "claude-opus-4.8")
    assert "model: claude-opus-4.8" in pinned

    removed = rewrite_agent_model(pinned, None)
    assert "model:" not in removed

    existing = "---\ndescription: Agent\nmodel: gpt-5.4\nmaxTurns: 100\n---\n\nBody\n"
    replaced = rewrite_agent_model(existing, "claude-opus-4.8")
    assert replaced.count("model: claude-opus-4.8") == 1


def test_rewrite_agent_name_replaces_existing_name_line() -> None:
    original = "---\nname: code\ndescription: Main agent\n---\n\nBody\n"
    renamed = rewrite_agent_name(original, "atelier:code")
    assert "name: atelier:code" in renamed
    assert "name: code" not in renamed


def test_workspace_copilot_agent_uses_project_model(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = workspace / ".atelier" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"models": {"hosts": {"copilot": {"roles": {"code": "claude-opus-4.8"}}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    text = workspace_copilot_agent_text("code", workspace)

    assert "model: claude-opus-4.8" in text


def test_workspace_copilot_agent_inherits_runtime_model_without_host_override(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = workspace / ".atelier" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"models": {"runtime": {"roles": {"code": "gpt-5.5"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    text = workspace_copilot_agent_text("code", workspace)

    assert "model: gpt-5.5" in text


def test_workspace_claude_agent_omits_model_for_auto(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = workspace / ".atelier" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"models": {"hosts": {"claude": {"roles": {"code": "auto"}}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    text = workspace_claude_agent_text("code", workspace)

    assert "name: atelier:code" in text
    assert "model:" not in text.split("---", 2)[1]


def test_workspace_claude_agent_omits_model_when_runtime_default_only(tmp_path: Path, monkeypatch) -> None:
    """Runtime-only model (no host override) should not inject model line."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = workspace / ".atelier" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"models": {"runtime": {"roles": {"code": "gpt-5.5"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    text = workspace_claude_agent_text("code", workspace)

    assert "name: atelier:code" in text
    assert "model:" not in text.split("---", 2)[1]


def test_workspace_claude_agent_injects_model_on_explicit_host_override(tmp_path: Path, monkeypatch) -> None:
    """Explicit hosts.claude.code override should inject the model and normalize it."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = workspace / ".atelier" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"models": {"hosts": {"claude": {"roles": {"code": "claude-opus-4.8"}}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    text = workspace_claude_agent_text("code", workspace)

    assert "name: atelier:code" in text
    assert "model: claude-opus-4-8" in text.split("---", 2)[1]


def test_write_workspace_copilot_agents_projects_role_files_and_default_agent(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    written = write_workspace_copilot_agents(workspace)

    assert workspace / ".github" / "agents" / "atelier.code.agent.md" in written
    assert workspace / ".github" / "agents" / "atelier.execute.agent.md" in written
    vs_code_settings = workspace / ".vscode" / "settings.json"
    assert vs_code_settings in written
    assert vs_code_settings.exists()
    payload = json.loads(vs_code_settings.read_text(encoding="utf-8"))
    assert payload.get("github.copilot.chat.defaultAgent") == "atelier.code"


def test_write_workspace_claude_overrides_uses_namespaced_filenames(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    written = write_workspace_claude_overrides(workspace)

    assert workspace / ".claude" / "agents" / "atelier.code.md" in written


def test_write_workspace_opencode_agents_projects_workspace_files(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    written = write_workspace_opencode_agents(workspace)

    assert workspace / ".opencode" / "agents" / "atelier.code.md" in written
    assert workspace / ".opencode" / "agents" / "atelier.review.md" in written


def test_write_workspace_codex_agents_projects_workspace_files(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    written = write_workspace_codex_agents(workspace)
    content = (workspace / ".codex" / "agents" / "atelier.code.toml").read_text(encoding="utf-8")

    assert workspace / ".codex" / "agents" / "atelier.code.toml" in written
    assert 'name = "atelier.code"' in content
