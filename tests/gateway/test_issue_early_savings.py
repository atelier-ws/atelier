from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "integrations" / "claude" / "plugin" / "scripts" / "statusline.sh"
_SOURCE_PYTHON = str(ROOT / ".venv" / "bin" / "python")


def _run_statusline(root: Path, payload: dict[str, object], *, env_extra: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env.update(
        {
            "ATELIER_ROOT": str(root),
            "ATELIER_STORE_ROOT": str(root),
            "ATELIER_NO_COLOR": "1",
            "ATELIER_PYTHON": _SOURCE_PYTHON,
        }
    )
    env.update(env_extra or {})
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _payload(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "model": {"display_name": "Sonnet"},
        "context_window": {
            "used_percentage": 0,
            "current_usage": {"input_tokens": 0, "output_tokens": 0},
        },
        "cost": {"total_cost_usd": 0.0, "total_duration_ms": 0},
    }


def test_statusline_does_not_borrow_from_stale_bridge_in_new_main_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # New sid
    new_sid = "a1b2c3d4-e5f6-47a8-b9c0-d1e2f3a4b5c6"

    # Old session has savings
    old_sid = "3d829763-d5f4-47ce-b45f-8006fe864df2"
    sidecar = tmp_path / "session_stats" / "claude"
    sidecar.mkdir(parents=True)
    (sidecar / f"{old_sid}.jsonl").write_text(
        json.dumps({"tool": "search", "tokens": 603, "calls": 0}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "auth.json").write_text(json.dumps({"authenticated": True}), encoding="utf-8")

    # Run statusline for the NEW session (no parent relationship possible)
    output = _run_statusline(tmp_path, _payload(new_sid), env_extra={"CLAUDE_WORKSPACE_ROOT": str(workspace)})

    # It should report 0 savings
    assert "(603)" not in output
    assert "(0)" in output


def test_statusline_borrows_for_subagents_via_transcript(tmp_path: Path) -> None:
    # Need to setup transcript for subagent linking
    home = tmp_path / "home"
    config_dir = home / ".claude"
    projects_dir = config_dir / "projects" / "workspace"
    projects_dir.mkdir(parents=True)

    parent_sid = "3d829763-d5f4-47ce-b45f-8006fe864df2"
    subagent_sid = "agent-a5c5037039b7b4621"

    # Transcript for subagent linking to parent
    transcript = {"sessionId": parent_sid}
    (projects_dir / f"{subagent_sid}.jsonl").write_text(json.dumps(transcript) + "\n", encoding="utf-8")

    # Parent session has savings
    sidecar = tmp_path / "session_stats" / "claude"
    sidecar.mkdir(parents=True)
    (sidecar / f"{parent_sid}.jsonl").write_text(
        json.dumps({"tool": "search", "tokens": 603, "calls": 0}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "auth.json").write_text(json.dumps({"authenticated": True}), encoding="utf-8")

    # Run statusline for the SUBAGENT session
    env = {"CLAUDE_CONFIG_DIR": str(config_dir)}
    output = _run_statusline(tmp_path, _payload(subagent_sid), env_extra=env)

    # It SHOULD borrow the 603 savings from the parent transcript
    assert "(603)" in output
