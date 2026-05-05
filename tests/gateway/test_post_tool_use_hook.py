from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path("integrations/claude/plugin/hooks/post_tool_use_compact.py")


def test_post_tool_use_compact_hook_returns_compacted_output(tmp_path: Path) -> None:
    atelier_root = tmp_path / ".atelier"
    atelier_root.mkdir()
    (atelier_root / "config.toml").write_text(
        "[compact]\nthreshold_tokens = 500\nbudget_tokens = 120\n",
        encoding="utf-8",
    )
    repeated_output = "\n".join(f"line {index}: value" for index in range(300))
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "printf many-lines"},
        "tool_response": {"stdout": repeated_output},
    }

    env = os.environ.copy()
    env["ATELIER_ROOT"] = str(atelier_root)
    env["PYTHONPATH"] = "src"
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
    rendered = json.loads(result.stdout)
    compact_result = rendered["atelierCompactToolOutput"]
    assert rendered["toolOutput"] == compact_result["compacted"]
    assert compact_result["method"] == "deterministic_truncate"
    assert compact_result["original_tokens"] > compact_result["compacted_tokens"]
    assert "Re-run command" in compact_result["recovery_hint"]


def test_post_tool_use_compact_hook_passthroughs_small_output(tmp_path: Path) -> None:
    atelier_root = tmp_path / ".atelier"
    atelier_root.mkdir()
    payload = {"tool_name": "Read", "tool_response": {"content": "short output"}}

    env = os.environ.copy()
    env["ATELIER_ROOT"] = str(atelier_root)
    env["PYTHONPATH"] = "src"
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
    assert result.stdout == ""
