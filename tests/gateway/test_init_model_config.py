from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from atelier.gateway.cli import cli
from atelier.gateway.cli.commands import admin as admin_command
from atelier.gateway.cli.commands import code as code_command


def test_init_can_configure_workspace_models_and_host_surfaces(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(admin_command, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        admin_command.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command in {"code", "claude"} else None,
    )

    root = tmp_path / ".atelier-store"
    user_input = "y\n" + ("\n" * 8) + "n\n"
    result = CliRunner().invoke(
        cli,
        ["--root", str(root), "init", "--no-seed", "--no-index", "--configure-models"],
        input=user_input,
    )

    assert result.exit_code == 0, result.output
    assert "Customize role models" in result.output
    assert "Suggested models:" not in result.output
    settings = workspace / ".atelier" / "settings.json"
    assert settings.exists()
    assert (workspace / ".github" / "agents" / "atelier.code.agent.md").exists()
    assert (workspace / ".github" / "agents" / "atelier.execute.agent.md").exists()
    copilot_agent = (workspace / ".github" / "agents" / "atelier.code.agent.md").read_text(encoding="utf-8")
    assert "model: claude-opus-4.8" in copilot_agent.split("---", 2)[1]
    code_agent = (workspace / ".claude" / "agents" / "atelier.code.md").read_text(encoding="utf-8")
    # No model line when only runtime defaults are set (no host override)
    assert "model:" not in code_agent.split("---", 2)[1]
    settings_payload = json.loads(settings.read_text(encoding="utf-8"))
    assert "hosts" not in settings_payload["models"]
    assert not (workspace / ".claude" / "skills" / "code" / "SKILL.md").exists()
    assert (workspace / ".claude" / "skills" / "orchestrate" / "SKILL.md").exists()


def test_init_accepts_auto_and_custom_host_role_values(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(admin_command, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        admin_command.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command in {"code", "claude"} else None,
    )

    root = tmp_path / ".atelier-store"
    user_input = "y\n" + ("\n" * 8) + "y\ny\nauto\nmy-copilot-execute\n" + ("\n" * 5) + ("n\n" * 6)
    result = CliRunner().invoke(
        cli,
        ["--root", str(root), "init", "--no-seed", "--no-index", "--configure-models"],
        input=user_input,
    )

    assert result.exit_code == 0, result.output
    settings = json.loads((workspace / ".atelier" / "settings.json").read_text(encoding="utf-8"))
    assert settings["models"]["hosts"]["copilot"]["roles"]["code"] == "auto"
    assert settings["models"]["hosts"]["copilot"]["roles"]["execute"] == "my-copilot-execute"
    assert "claude" not in settings["models"]["hosts"]


def test_init_uses_progress_bootstrap_for_code_index(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    monkeypatch.chdir(workspace)

    seen: dict[str, str] = {}

    monkeypatch.setattr(code_command, "_code_context_engine", lambda repo_root: object())

    def fake_index_repo_with_progress(engine, **kwargs):
        seen["description"] = kwargs["description"]
        seen["success_description"] = kwargs["success_description"]
        return {"files_indexed": 3, "symbols_indexed": 9, "imports_indexed": 2}

    monkeypatch.setattr(code_command, "_index_repo_with_progress", fake_index_repo_with_progress)

    root = tmp_path / ".atelier-store"
    result = CliRunner().invoke(cli, ["--root", str(root), "init", "--no-seed"])

    assert result.exit_code == 0, result.output
    assert seen == {
        "description": "Bootstrapping code index",
        "success_description": "Code index ready",
    }
    assert "indexed 3 files, 9 symbols (2 imports)" in result.output


def test_init_installs_project_agents_md_and_codex_agents(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(
        admin_command.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "codex" else None,
    )

    root = tmp_path / ".atelier-store"
    result = CliRunner().invoke(cli, ["--root", str(root), "init", "--no-seed", "--no-index"])

    assert result.exit_code == 0, result.output
    assert "[agents_md] updated AGENTS.md" in result.output
    assert "[codex] updated" in result.output
    agents_md = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "Codex may defer MCP tools behind `tool_search`" in agents_md
    assert (workspace / ".codex" / "agents" / "atelier.code.toml").exists()
    codex_config = (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[agents.atelier_code]" in codex_config
    assert f'config_file = "{workspace / ".codex" / "agents" / "atelier.code.toml"}"' in codex_config
