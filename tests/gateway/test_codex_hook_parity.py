"""In-process unit tests for Codex lifecycle-hook parity (Phase 1).

These exercise the ``build_codex_*`` runtime functions directly (no subprocess),
so they run in the default fast suite. The subprocess-level smoke tests live in
``test_codex_plugin_hooks.py`` (marked slow).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atelier.core.capabilities import plugin_runtime
from atelier.core.capabilities.grounded_loop.grounding_evidence import record_grounding_evidence

ROOT = Path(__file__).resolve().parents[2]


def _seed_run_file(root: Path, session_id: str) -> Path:
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run_file = runs / f"{session_id}.json"
    run_file.write_text(
        json.dumps({"session_id": session_id, "events": [], "files_touched": []}),
        encoding="utf-8",
    )
    return run_file


def _write_session_state(root: Path, payload: dict, state: dict) -> None:
    path = plugin_runtime._codex_session_state_path(root, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def _events(root: Path, session_id: str) -> list[dict]:
    data = json.loads((root / "runs" / f"{session_id}.json").read_text(encoding="utf-8"))
    return data["events"]


# --------------------------------------------------------------------------
# tool normalization
# --------------------------------------------------------------------------
def test_normalize_codex_tool_maps_native_and_mcp_tools() -> None:
    assert plugin_runtime._normalize_codex_tool("apply_patch") == "edit"
    assert plugin_runtime._normalize_codex_tool("mcp__atelier__edit") == "edit"
    assert plugin_runtime._normalize_codex_tool("mcp__plugin_atelier_atelier__Edit") == "edit"
    assert plugin_runtime._normalize_codex_tool("shell") == "bash"
    assert plugin_runtime._normalize_codex_tool("local_shell") == "bash"
    assert plugin_runtime._normalize_codex_tool("read") == "read"
    assert plugin_runtime._normalize_codex_tool("web_search") == "other"


# --------------------------------------------------------------------------
# PreToolUse grounding gate
# --------------------------------------------------------------------------
def test_pre_tool_use_allows_when_bench_gate_off(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"file_path": "alembic/versions/0001.py"},
        "cwd": str(tmp_path),
    }
    assert plugin_runtime.build_codex_pre_tool_use_output(root, payload).get("no_output") is True


def test_pre_tool_use_denies_ungrounded_risky_edit_under_bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_runtime, "_codex_bench_gate_enabled", lambda: True)
    root = tmp_path / ".atelier"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "apply_patch",
        "tool_input": {"file_path": "alembic/versions/0001.py"},
        "cwd": str(workspace),
    }
    out = plugin_runtime.build_codex_pre_tool_use_output(root, payload)
    hook = out.get("hookSpecificOutput") or {}
    assert hook.get("permissionDecision") == "deny"
    assert hook.get("hookEventName") == "PreToolUse"
    assert "ground this edit" in hook.get("permissionDecisionReason", "")


def test_pre_tool_use_allows_grounded_risky_edit_under_bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_runtime, "_codex_bench_gate_enabled", lambda: True)
    root = tmp_path / ".atelier"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = "alembic/versions/0001.py"
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "apply_patch",
        "tool_input": {"file_path": target},
        "cwd": str(workspace),
    }
    state = record_grounding_evidence(
        {}, session_id="s1", tool_name="read", targets=[target], workspace_root=str(workspace)
    )
    _write_session_state(root, payload, state)
    assert plugin_runtime.build_codex_pre_tool_use_output(root, payload).get("no_output") is True


def test_pre_tool_use_ignores_non_edit_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_runtime, "_codex_bench_gate_enabled", lambda: True)
    root = tmp_path / ".atelier"
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "shell",
        "tool_input": {"command": "ls"},
        "cwd": str(tmp_path),
    }
    assert plugin_runtime.build_codex_pre_tool_use_output(root, payload).get("no_output") is True


def test_pre_tool_use_allows_non_risky_edit_under_bench(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin_runtime, "_codex_bench_gate_enabled", lambda: True)
    root = tmp_path / ".atelier"
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "apply_patch",
        "tool_input": {"file_path": "src/util.py"},
        "cwd": str(tmp_path),
    }
    assert plugin_runtime.build_codex_pre_tool_use_output(root, payload).get("no_output") is True


# --------------------------------------------------------------------------
# PostToolUse run-ledger capture + failure rescue
# --------------------------------------------------------------------------
def test_post_tool_use_records_file_edit(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": "apply_patch",
        "tool_input": {"file_path": "a.py", "old_string": "x = 1", "new_string": "x = 2"},
        "cwd": str(tmp_path),
    }
    out = plugin_runtime.build_codex_post_tool_use_ledger_output(root, payload)
    assert out.get("no_output") is True
    events = _events(root, session_id)
    file_edits = [e for e in events if e["kind"] == "file_edit"]
    assert len(file_edits) == 1
    assert file_edits[0]["payload"]["path"] == "a.py"
    assert "x = 2" in file_edits[0]["payload"]["diff"]
    data = json.loads((root / "runs" / f"{session_id}.json").read_text(encoding="utf-8"))
    assert "a.py" in data["files_touched"]


def test_post_tool_use_ignores_read_tools(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": "read",
        "tool_input": {"path": "a.py"},
        "cwd": str(tmp_path),
    }
    assert plugin_runtime.build_codex_post_tool_use_ledger_output(root, payload).get("no_output") is True
    assert _events(root, session_id) == []


def test_post_tool_use_records_command_and_rescues_on_repeat_failure(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": "shell",
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"stderr": "AssertionError: boom", "exit_code": 1},
        "cwd": str(tmp_path),
    }
    first = plugin_runtime.build_codex_post_tool_use_ledger_output(root, payload)
    assert first.get("no_output") is True
    second = plugin_runtime.build_codex_post_tool_use_ledger_output(root, payload)
    assert "rescue" in second.get("systemMessage", "").lower()
    commands = [e for e in _events(root, session_id) if e["kind"] == "command_result"]
    assert len(commands) == 2
    assert commands[0]["payload"]["ok"] is False
    assert commands[0]["payload"]["command"] == "pytest -q"


def test_post_tool_use_successful_command_is_silent(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": "shell",
        "tool_input": {"command": "echo hi"},
        "tool_response": {"stdout": "hi", "exit_code": 0},
        "cwd": str(tmp_path),
    }
    out = plugin_runtime.build_codex_post_tool_use_ledger_output(root, payload)
    assert out.get("no_output") is True
    commands = [e for e in _events(root, session_id) if e["kind"] == "command_result"]
    assert commands[0]["payload"]["ok"] is True


# --------------------------------------------------------------------------
# Compaction lifecycle
# --------------------------------------------------------------------------
def test_post_compact_bumps_epoch_and_notes(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    payload = {
        "hook_event_name": "PostCompact",
        "session_id": session_id,
        "cwd": str(tmp_path),
        "trigger": "auto",
    }
    assert plugin_runtime.build_codex_post_compact_output(root, payload).get("no_output") is True
    state = json.loads(plugin_runtime._codex_session_state_path(root, payload).read_text(encoding="utf-8"))
    assert state["compaction_epoch"] == 1
    notes = [e for e in _events(root, session_id) if e["kind"] == "note"]
    assert any("completed" in e["summary"] for e in notes)


def test_pre_compact_snapshots_occupancy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "atelier.gateway.hosts.context_state.host_context_state",
        lambda host, session_id: (123_000, "gpt-5.5"),
    )
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    payload = {
        "hook_event_name": "PreCompact",
        "session_id": session_id,
        "cwd": str(tmp_path),
        "trigger": "manual",
    }
    assert plugin_runtime.build_codex_pre_compact_output(root, payload).get("no_output") is True
    state = json.loads(plugin_runtime._codex_session_state_path(root, payload).read_text(encoding="utf-8"))
    assert state["precompact_occupancy"] == 123_000
    assert state["precompact_pending"] is True
    notes = [e for e in _events(root, session_id) if e["kind"] == "note"]
    assert any("starting" in e["summary"] for e in notes)


# --------------------------------------------------------------------------
# UserPromptSubmit + Stop enrichment
# --------------------------------------------------------------------------
def test_user_prompt_records_agent_message_and_last_prompt(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "prompt": "Refactor the parser",
        "cwd": str(tmp_path),
    }
    plugin_runtime._codex_enrich_user_prompt(root, payload)
    state = json.loads(plugin_runtime._codex_session_state_path(root, payload).read_text(encoding="utf-8"))
    assert state["last_user_prompt"] == "Refactor the parser"
    messages = [e for e in _events(root, session_id) if e["kind"] == "agent_message"]
    assert len(messages) == 1
    assert messages[0]["payload"]["role"] == "user"
    assert messages[0]["payload"]["prompt"] == "Refactor the parser"


# --------------------------------------------------------------------------
# PermissionRequest auto-deny (Codex-exclusive)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        "sudo rm -rf /",
        "rm -rf /usr",
        "rm -rf /etc/",
        "rm --recursive --force /",
        "git push --force origin main",
        "git push -f",
        "git push -f origin main",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
    ],
)
def test_permission_request_denies_destructive_commands(tmp_path: Path, command: str) -> None:
    payload = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "shell",
        "tool_input": {"command": command},
    }
    out = plugin_runtime.build_codex_permission_request_output(tmp_path / ".atelier", payload)
    assert (out.get("hookSpecificOutput") or {}).get("behavior") == "deny", command


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build/",
        "rm -rf ./node_modules",
        "rm -rf /usr/local/foo",
        "git push --force-with-lease",
        "git push origin main",
        "ls -la",
        "pytest -q",
    ],
)
def test_permission_request_allows_safe_commands(tmp_path: Path, command: str) -> None:
    payload = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "shell",
        "tool_input": {"command": command},
    }
    assert plugin_runtime.build_codex_permission_request_output(tmp_path / ".atelier", payload).get("no_output") is True


def test_permission_request_ignores_non_bash_tools(tmp_path: Path) -> None:
    payload = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "apply_patch",
        "tool_input": {"file_path": "a.py"},
    }
    assert plugin_runtime.build_codex_permission_request_output(tmp_path / ".atelier", payload).get("no_output") is True


# --------------------------------------------------------------------------
# codex exec --json telemetry collector (Codex-exclusive)
# --------------------------------------------------------------------------
def test_ingest_codex_exec_events_records_command_and_file(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    session_id = "run1"
    _seed_run_file(root, session_id)
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "command_execution", "command": "pytest -q", "exit_code": 1, "output": "boom"},
            }
        ),
        json.dumps({"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "a.py"}]}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10}}),
        "not json",
    ]
    count = plugin_runtime.ingest_codex_exec_events(root, session_id, lines)
    assert count == 2
    events = _events(root, session_id)
    kinds = {e["kind"] for e in events}
    assert kinds == {"command_result", "file_edit"}
    cmd = next(e for e in events if e["kind"] == "command_result")
    assert cmd["payload"]["ok"] is False
    assert cmd["payload"]["command"] == "pytest -q"
    data = json.loads((root / "runs" / f"{session_id}.json").read_text(encoding="utf-8"))
    assert "a.py" in data["files_touched"]


def test_ingest_codex_exec_events_noop_without_session(tmp_path: Path) -> None:
    assert plugin_runtime.ingest_codex_exec_events(tmp_path / ".atelier", "", ["{}"]) == 0


# --------------------------------------------------------------------------
# Statusline savings line
# --------------------------------------------------------------------------
def test_codex_savings_line_is_14_field_parseable(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir()
    line = plugin_runtime.build_codex_savings_line(root, "missing-session")
    fields = line.split("|")
    assert len(fields) == 14, line
    assert fields[0].startswith("$")  # saved_usd
    assert fields[10].startswith("$")  # carry_usd
    assert fields[12].endswith("%")  # carry_pct
    assert fields[13].endswith("%")  # saved_pct


# --------------------------------------------------------------------------
# Per-role Codex agents
# --------------------------------------------------------------------------
def test_write_codex_agents_generates_all_surfaced_roles(tmp_path: Path) -> None:
    from atelier.core.capabilities.workspace_host_overrides import write_codex_agents

    target = tmp_path / "agents"
    written = write_codex_agents(target, repo_root=ROOT)
    assert len(written) == 7
    names = {p.name for p in written}
    assert {"atelier.code.toml", "atelier.explore.toml", "atelier.solve.toml"} <= names
    text = (target / "atelier.code.toml").read_text(encoding="utf-8")
    assert 'name = "atelier.code"' in text
    assert "developer_instructions" in text


def test_render_codex_agent_toml_escapes_hostile_body() -> None:
    import tomllib

    from atelier.core.capabilities.workspace_host_overrides import _render_codex_agent_toml

    # Body with everything that breaks naive TOML rendering: a regex backslash,
    # a Windows path, a bare quote, and a literal triple-quote run.
    body = 'use regex \\d+ and path C:\\temp; quote " and triple """ end'
    description = 'a "quoted" desc with \\ backslash'
    rendered = _render_codex_agent_toml("code", description, body, "gpt-5.5")
    parsed = tomllib.loads(rendered)  # must not raise
    assert parsed["name"] == "atelier.code"
    assert parsed["model"] == "gpt-5.5"
    assert parsed["description"] == 'a "quoted" desc with \\ backslash'
    instr = parsed["developer_instructions"]
    assert "\\d+" in instr  # literal backslash-d survived (not a TOML escape)
    assert "C:\\temp" in instr
    assert '"""' in instr  # literal triple-quote round-tripped


def test_write_codex_agents_prunes_stale_roles(tmp_path: Path) -> None:
    from atelier.core.capabilities.workspace_host_overrides import write_codex_agents

    target = tmp_path / "agents"
    target.mkdir()
    (target / "atelier.removed.toml").write_text('name = "atelier.removed"\n', encoding="utf-8")
    write_codex_agents(target, repo_root=ROOT)
    assert not (target / "atelier.removed.toml").exists()


# --------------------------------------------------------------------------
# Manifest wiring
# --------------------------------------------------------------------------
def test_codex_hooks_manifest_includes_new_lifecycle_events() -> None:
    data = json.loads((ROOT / "integrations" / "codex" / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    for event in (
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PreCompact",
        "PostCompact",
        "Stop",
    ):
        assert event in data["hooks"], f"missing hooks.json event: {event}"
    assert "PermissionRequest" in data["hooks"]
    rendered = json.dumps(data)
    assert "pre_tool_use.py" in rendered
    assert "compact.py" in rendered
    assert "permission_request.py" in rendered
    assert "${PLUGIN_ROOT}/hooks/" in rendered
    assert "__ATELIER_PYTHON__" in rendered
    assert "__ATELIER_REPO_SRC__" in rendered
