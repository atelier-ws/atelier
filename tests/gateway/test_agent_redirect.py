from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path("integrations/claude/plugin/hooks/agent_redirect.py")


def _run(subagent_type: str) -> str:
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": subagent_type, "prompt": "x"}}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    return result.stdout.strip()


def test_explore_is_rewritten_to_atelier_explore() -> None:
    out = json.loads(_run("Explore"))["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert out["updatedInput"]["subagent_type"] == "atelier:explore"
    assert out["updatedInput"]["prompt"] == "x"  # other input preserved
    assert "atelier:explore" in out["additionalContext"]


def test_plan_is_rewritten_to_atelier_plan() -> None:
    out = json.loads(_run("Plan"))["hookSpecificOutput"]
    assert out["updatedInput"]["subagent_type"] == "atelier:plan"


def test_atelier_agent_is_untouched() -> None:
    assert _run("atelier:code") == ""


def test_general_purpose_is_untouched() -> None:
    assert _run("general-purpose") == ""
