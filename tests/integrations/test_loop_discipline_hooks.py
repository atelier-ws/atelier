"""Tests for the loop-discipline plugin hooks (cycle-cap + read-after-edit guard).

The hooks are standalone scripts that read a JSON payload on stdin and print a
JSON decision on stdout, so we exercise them as subprocesses with crafted
payloads -- isolating session state under a per-test ATELIER_ROOT.

``loop_discipline_post.py`` (PostToolUse) and ``pre_tool_discipline.py``
(PreToolUse) share one workspace-hash-keyed state file, so passing the same
CLAUDE_WORKSPACE_ROOT + ATELIER_ROOT lets them coordinate the cycle-cap gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[2] / "integrations" / "claude" / "plugin" / "hooks"


def _run(hook: str, payload: dict, tmp_path: Path, env_extra: dict | None = None) -> str:
    env = {
        **os.environ,
        "CLAUDE_WORKSPACE_ROOT": str(tmp_path),
        "ATELIER_ROOT": str(tmp_path / ".atelier"),
        **(env_extra or {}),
    }
    proc = subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _fail_shell() -> dict:
    return {
        "tool_name": "mcp__atelier__shell",
        "tool_input": {"command": "cargo test"},
        "tool_response": {"content": [{"type": "text", "text": "exit_code=1\nerror[E0308]: mismatched types"}]},
    }


def _pass_shell() -> dict:
    return {
        "tool_name": "mcp__atelier__shell",
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"content": [{"type": "text", "text": "exit_code=0\n5 passed"}]},
    }


def _test_shell() -> dict:
    """A PreToolUse payload: a test/build command about to run (no response yet)."""
    return {"tool_name": "mcp__atelier__shell", "tool_input": {"command": "cargo test"}}


def _read(path: str, **extra: object) -> dict:
    return {"tool_name": "mcp__atelier__read", "tool_input": {"path": path, **extra}}


def test_cycle_cap_nudges_after_three_consecutive_failures(tmp_path: Path) -> None:
    assert _run("loop_discipline_post.py", _fail_shell(), tmp_path) == ""
    assert _run("loop_discipline_post.py", _fail_shell(), tmp_path) == ""
    out = _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    data = json.loads(out)
    assert "consecutive test/build failures" in data["hookSpecificOutput"]["additionalContext"]
    assert data["hookSpecificOutput"]["hookEventName"] == "PostToolUse"


def test_cycle_cap_nudge_fires_once_at_threshold(tmp_path: Path) -> None:
    # Nudge fires only at the crossing (streak == threshold); the streak no longer
    # resets, so further failures stay silent (and the gate stays armed).
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    out = _run("loop_discipline_post.py", _fail_shell(), tmp_path)  # crosses -> nudge
    assert "consecutive test/build failures" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    # Fourth failure: above threshold, no second nudge.
    assert _run("loop_discipline_post.py", _fail_shell(), tmp_path) == ""


def test_cycle_cap_streak_resets_on_pass(tmp_path: Path) -> None:
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    _run("loop_discipline_post.py", _pass_shell(), tmp_path)  # resets streak to 0
    assert _run("loop_discipline_post.py", _fail_shell(), tmp_path) == ""
    assert _run("loop_discipline_post.py", _fail_shell(), tmp_path) == ""
    out = _run("loop_discipline_post.py", _fail_shell(), tmp_path)  # crosses again -> nudge
    assert "consecutive test/build failures" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_cycle_cap_ignores_non_test_commands(tmp_path: Path) -> None:
    grep = {
        "tool_name": "mcp__atelier__shell",
        "tool_input": {"command": "grep -rn foo src"},
        "tool_response": {"content": [{"type": "text", "text": "exit_code=1\nno match"}]},
    }
    for _ in range(4):
        assert _run("loop_discipline_post.py", grep, tmp_path) == ""


def test_cycle_cap_blocks_test_runs_until_a_read_clears_the_gate(tmp_path: Path) -> None:
    # 3 consecutive failures arm the gate (the third also emits the nudge).
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)

    # A test run is now hard-blocked by the PreToolUse hook.
    out = _run("pre_tool_discipline.py", _test_shell(), tmp_path)
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "consecutive test/build failures" in data["reason"]

    # Any file read clears the gate (the re-grounding step we want).
    assert _run("pre_tool_discipline.py", _read("src/lib.rs", range="L1-L40"), tmp_path) == ""

    # The same test run is now allowed.
    assert _run("pre_tool_discipline.py", _test_shell(), tmp_path) == ""


def test_cycle_cap_block_opts_out_via_env(tmp_path: Path) -> None:
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)  # gate armed
    # Master opt-out: no block even with the gate armed.
    assert _run("pre_tool_discipline.py", _test_shell(), tmp_path, {"ATELIER_LOOP_DISCIPLINE": "0"}) == ""


def test_cycle_cap_does_not_block_test_runs_when_gate_disarmed(tmp_path: Path) -> None:
    # Below threshold -> gate not armed -> test run allowed.
    _run("loop_discipline_post.py", _fail_shell(), tmp_path)
    assert _run("pre_tool_discipline.py", _test_shell(), tmp_path) == ""


def test_read_after_edit_blocks_expand_reread_of_edited_file(tmp_path: Path) -> None:
    edit = {
        "tool_name": "mcp__atelier__edit",
        "tool_input": {"edits": [{"file_path": "shop/pricing.py", "old_string": "a", "new_string": "b"}]},
    }
    assert _run("loop_discipline_post.py", edit, tmp_path) == ""  # records the edit

    expand_reread = _read("shop/pricing.py", expand=True)
    out = _run("pre_tool_discipline.py", expand_reread, tmp_path)
    assert json.loads(out)["decision"] == "block"

    # a targeted range read of the same file is allowed
    assert _run("pre_tool_discipline.py", _read("shop/pricing.py", range="L1-L20"), tmp_path) == ""

    # an expand read of a file NOT edited this session is allowed
    assert _run("pre_tool_discipline.py", _read("shop/other.py", expand=True), tmp_path) == ""

    # opt-out via the read-after-edit-specific env
    assert _run("pre_tool_discipline.py", expand_reread, tmp_path, {"ATELIER_READ_AFTER_EDIT_GUARD": "0"}) == ""

    # master opt-out also disables it
    assert _run("pre_tool_discipline.py", expand_reread, tmp_path, {"ATELIER_LOOP_DISCIPLINE": "0"}) == ""


def test_read_after_edit_no_block_without_prior_edit(tmp_path: Path) -> None:
    expand_reread = _read("shop/pricing.py", expand=True)
    assert _run("pre_tool_discipline.py", expand_reread, tmp_path) == ""
