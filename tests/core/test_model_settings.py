from __future__ import annotations

import json
from pathlib import Path

from atelier.core.capabilities.model_settings import (
    global_model_settings_path,
    load_model_settings,
    resolve_explicit_host_model,
    resolve_host_model,
    resolve_runtime_model,
    workspace_model_settings_path,
)


def test_workspace_settings_override_global(tmp_path: Path, monkeypatch) -> None:
    global_root = tmp_path / "global-root"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(global_root))
    global_path = global_model_settings_path()
    global_path.parent.mkdir(parents=True, exist_ok=True)
    global_path.write_text(
        json.dumps(
            {
                "models": {
                    "runtime": {"roles": {"code": "gpt-5.4"}},
                    "hosts": {"copilot": {"roles": {"code": "gpt-5.4"}}},
                }
            }
        ),
        encoding="utf-8",
    )
    local_path = workspace_model_settings_path(workspace)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(
        json.dumps(
            {
                "models": {
                    "runtime": {"roles": {"code": "claude-opus-4.8"}},
                    "hosts": {"copilot": {"roles": {"code": "claude-opus-4.8"}}},
                }
            }
        ),
        encoding="utf-8",
    )

    merged = load_model_settings(workspace)
    assert merged["models"]["runtime"]["roles"]["code"] == "claude-opus-4.8"
    assert resolve_runtime_model("code", workspace) == "claude-opus-4.8"
    assert resolve_host_model("copilot", "code", workspace_root=workspace) == "claude-opus-4.8"


def test_host_auto_resolves_to_no_explicit_model(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    local_path = workspace_model_settings_path(workspace)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(
        json.dumps({"models": {"hosts": {"claude": {"roles": {"code": "auto"}}}}}),
        encoding="utf-8",
    )

    assert resolve_host_model("claude", "code", workspace_root=workspace) is None
    assert resolve_runtime_model("code", workspace) == "claude-opus-4.8"


def test_host_without_override_inherits_runtime_model(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    local_path = workspace_model_settings_path(workspace)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(
        json.dumps({"models": {"runtime": {"roles": {"code": "gpt-5.5"}}}}),
        encoding="utf-8",
    )

    assert resolve_host_model("opencode", "code", workspace_root=workspace) == "gpt-5.5"


def test_legacy_all_auto_host_stub_inherits_runtime_model(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    local_path = workspace_model_settings_path(workspace)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(
        json.dumps(
            {
                "models": {
                    "runtime": {"roles": {"code": "gpt-5.5"}},
                    "hosts": {
                        "claude": {
                            "roles": {
                                "code": "auto",
                                "execute": "auto",
                                "explore": "auto",
                                "plan": "auto",
                                "research": "auto",
                                "review": "auto",
                                "solve": "auto",
                            }
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    assert resolve_host_model("claude", "code", workspace_root=workspace) == "gpt-5.5"


def test_shipped_host_default_pins_explore_and_research_cheap(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))

    assert resolve_explicit_host_model("claude", "explore", workspace_root=workspace) == "claude-haiku-4.5"
    assert resolve_explicit_host_model("claude", "research", workspace_root=workspace) == "claude-haiku-4.5"
    assert resolve_explicit_host_model("codex", "explore", workspace_root=workspace) == "gpt-5.4-mini"
    # Coding/judgment roles inherit the session model (no pin).
    assert resolve_explicit_host_model("claude", "code", workspace_root=workspace) is None
    assert resolve_explicit_host_model("claude", "plan", workspace_root=workspace) is None


def test_explicit_auto_overrides_shipped_host_default(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(tmp_path / "global-root"))
    local_path = workspace_model_settings_path(workspace)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(
        json.dumps({"models": {"hosts": {"claude": {"roles": {"explore": "auto"}}}}}),
        encoding="utf-8",
    )

    assert resolve_explicit_host_model("claude", "explore", workspace_root=workspace) is None
