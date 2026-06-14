from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path("integrations/claude/plugin/hooks/edit_batching_nudge.py")


def _run(root: Path, tool_name: str, edits_count: int) -> str:
    env = os.environ.copy()
    env["ATELIER_ROOT"] = str(root)
    env["PYTHONPATH"] = "src"
    tool_input: dict = {"edits": [{"file_path": f"f{i}.py"} for i in range(edits_count)]}
    payload = {"tool_name": tool_name, "tool_input": tool_input}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    return result.stdout.strip()


def test_nudges_after_three_single_edits(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir()
    assert _run(root, "mcp__atelier__edit", 1) == ""
    assert _run(root, "mcp__atelier__edit", 1) == ""
    out = _run(root, "mcp__atelier__edit", 1)
    assert "single-edit" in out
    assert json.loads(out)["systemMessage"]
    # Already nudged this streak -> stays quiet on the 4th.
    assert _run(root, "mcp__atelier__edit", 1) == ""


def test_batch_edit_resets_streak(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir()
    _run(root, "mcp__atelier__edit", 1)
    _run(root, "mcp__atelier__edit", 1)
    assert _run(root, "mcp__atelier__edit", 3) == ""  # batch resets the streak
    assert _run(root, "mcp__atelier__edit", 1) == ""
    assert _run(root, "mcp__atelier__edit", 1) == ""
    out = _run(root, "mcp__atelier__edit", 1)
    assert "single-edit" in out


def test_ignores_non_edit_tools(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir()
    env = os.environ.copy()
    env["ATELIER_ROOT"] = str(root)
    env["PYTHONPATH"] = "src"
    payload = {"tool_name": "mcp__atelier__read", "tool_input": {"path": "x"}}
    for _ in range(3):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""
