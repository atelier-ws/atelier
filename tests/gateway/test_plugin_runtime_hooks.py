from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from atelier.core.capabilities.plugin_runtime import (
    aggregate_session_stats,
    apply_session_start_files,
    build_savings_report,
    session_start_bootstrap,
    status_line_choose_message,
    update_session_stats,
    write_plugin_setting,
)

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "integrations" / "claude" / "plugin" / "hooks"


def _run_hook(
    script: str,
    payload: dict[str, Any],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=merged_env,
    )


def test_tool_redirect_outputs_pretooluse_nudge_for_shell_reads() -> None:
    result = _run_hook(
        "tool_redirect.py",
        {"tool_name": "Bash", "tool_input": {"command": "cat src/app.ts"}},
    )

    output = json.loads(result.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse"
    assert hook_output["permissionDecision"] == "allow"
    assert "search" in hook_output["additionalContext"]


def test_edit_batching_nudge_emits_after_second_single_edit(tmp_path: Path) -> None:
    env = {"ATELIER_ROOT": str(tmp_path / ".atelier")}
    payload = {"session_id": "s1", "tool_input": {"edits": [{"file_path": "src/a.ts"}]}}

    first = _run_hook("edit_batching_nudge.py", payload, env=env)
    second = _run_hook("edit_batching_nudge.py", payload, env=env)

    assert first.stdout == ""
    output = json.loads(second.stdout)
    assert "2 individual Edit calls" in output["additionalContext"]
    assert (tmp_path / ".atelier" / "hook_state" / "edit-nudge-s1.json").exists()


def test_session_telemetry_persists_session_savings(tmp_path: Path) -> None:
    atelier_root = tmp_path / ".atelier"
    _run_hook(
        "session_telemetry.py",
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"edits": [{"file_path": "a.ts"}, {"file_path": "b.ts"}]},
        },
        env={"ATELIER_ROOT": str(atelier_root)},
    )

    stats = json.loads((atelier_root / "session_stats" / "s1.json").read_text(encoding="utf-8"))
    assert stats["total_tool_calls"] == 1
    assert stats["equivalent_baseline_calls"] > 1
    assert stats["savings"]["calls_saved"] > 0


def test_session_telemetry_tracks_usage_compaction_and_subagents(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"message": {"usage": {"input_tokens": 11, "output_tokens": 7}}}) + "\n",
        encoding="utf-8",
    )

    update_session_stats(
        root,
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "explore"},
            "usage": {"input_tokens": 5, "output_tokens": 3, "cache_read_input_tokens": 2},
            "transcript_path": str(transcript),
            "now_ms": 1000,
        },
    )
    update_session_stats(root, {"hook_event_name": "PreCompact", "session_id": "s1", "now_ms": 2000})
    update_session_stats(root, {"hook_event_name": "PostCompact", "session_id": "s1", "now_ms": 2750})
    update_session_stats(root, {"hook_event_name": "SubagentStop", "session_id": "s1", "now_ms": 3000})

    stats = json.loads((root / "session_stats" / "s1.json").read_text(encoding="utf-8"))
    assert stats["usage"]["input_tokens"] == 16
    assert stats["usage"]["output_tokens"] == 10
    assert stats["usage"]["cache_read_tokens"] == 2
    assert stats["compactions"] == 1
    assert stats["compaction_duration_ms"] == 750
    assert stats["subagents_started"] == 1
    assert stats["subagents_completed"] == 1
    assert stats["pending_subagents"] == 0
    assert (root / "session_events" / "s1.jsonl").exists()


def test_savings_report_merges_smart_state_and_session_stats(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir()
    (root / "smart_state.json").write_text(
        json.dumps({"savings": {"calls_avoided": 2, "tokens_saved": 1000}}),
        encoding="utf-8",
    )
    update_session_stats(
        root,
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s1",
            "tool_name": "SQL",
            "tool_input": {"queries": [{"sql": "select 1"}]},
        },
    )

    aggregate = aggregate_session_stats(root)
    report = build_savings_report(root, usd_per_1k_tokens=0.01)

    assert aggregate["session_count"] == 1
    assert report["calls_avoided"] >= 4
    assert report["tokens_saved"] >= 1000
    assert report["estimated_saved_usd"] >= 0.01
    assert "local estimates" in report["local_note"]


def test_session_start_bootstrap_applies_settings_auth_and_always_load(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    write_plugin_setting(root, "alwaysLoadTools", False)
    result = session_start_bootstrap(
        root,
        "/plugin",
        host_settings={},
        mcp_json={"mcpServers": {"atelier": {"alwaysLoad": True}}},
        payload={"session_id": "s1"},
    )

    assert result["host_settings"]["statusLine"]["command"].endswith("/plugin/scripts/statusline.sh")
    assert result["host_settings"]["atelier"]["spinnerVerbs"]
    assert result["host_settings"]["atelier"]["attribution"]["source"] == "Atelier"
    assert result["mcp_json"]["mcpServers"]["atelier"]["alwaysLoad"] is False
    assert result["auth"]["isAnonymous"] is True
    assert (root / "session_stats" / "s1.json").exists()


def test_apply_session_start_files_mutates_host_settings_and_plugin_mcp(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    config_dir = tmp_path / "config"
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    (plugin_root / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"atelier": {"alwaysLoad": False}}}),
        encoding="utf-8",
    )
    write_plugin_setting(root, "alwaysLoadTools", True)

    apply_session_start_files(root, plugin_root, config_dir=config_dir, payload={"session_id": "s2"})

    settings = json.loads((config_dir / "settings.json").read_text(encoding="utf-8"))
    mcp_json = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
    assert settings["statusLine"]["command"].endswith("/plugin/scripts/statusline.sh")
    assert mcp_json["mcpServers"]["atelier"]["alwaysLoad"] is True


def test_savings_report_includes_lifetime_baseline_and_free_plan(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir()
    (root / "lifetime_savings.json").write_text(json.dumps({"calls_saved": 8}), encoding="utf-8")
    (root / "baseline_estimate.json").write_text(
        json.dumps({"vanillaSessions": 6, "totalVanillaCostInUsd": 12.0}),
        encoding="utf-8",
    )
    (root / "free_plan.json").write_text(json.dumps({"remaining": 1.0, "limit": 10.0}), encoding="utf-8")

    report = build_savings_report(root)

    assert report["lifetime"]["calls_saved"] == 8
    assert report["baseline"]["available"] is True
    assert report["free_plan"]["usage_pct"] == 90.0


def test_status_line_priority_and_weighted_rotation() -> None:
    assert status_line_choose_message(update_flag={"fromVersion": "1", "toVersion": "2"})["message_family"] == "update"
    assert (
        status_line_choose_message(auth_present=False, update_flag={"fromVersion": "1", "toVersion": "2"})[
            "message_family"
        ]
        == "login"
    )
    assert status_line_choose_message(auth_present=False)["message_family"] == "login"
    assert status_line_choose_message(subscription_warning=True)["message_family"] == "subscription"
    assert status_line_choose_message(free_plan_remaining=1, free_plan_limit=10)["message_family"] == "free_plan"

    rotated = status_line_choose_message(
        session_id="s1",
        total_tool_calls=3,
        turn_count=6,
        enabled_families=["savings", "baseline", "tip"],
    )
    assert rotated["message_family"] in {"savings", "baseline", "tip"}
    assert rotated["rotation_skipped"] is False
