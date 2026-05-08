from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "integrations" / "claude" / "plugin"


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return text.split("---", 2)[1]


def test_plugin_mcp_server_is_loaded_at_session_start() -> None:
    config = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["atelier"]
    assert server["type"] == "stdio"
    assert server["alwaysLoad"] is True
    assert "${CLAUDE_PLUGIN_ROOT}" in " ".join(server["args"])


def test_main_agent_forces_atelier_file_tools() -> None:
    frontmatter = _frontmatter(PLUGIN / "agents" / "code.md")
    for tool_name in ["Read", "Edit", "Write", "Grep", "Glob", "NotebookEdit"]:
        assert tool_name in frontmatter
    assert "mcp__atelier__search" not in frontmatter


def test_explore_agent_is_read_only_and_uses_atelier_search() -> None:
    frontmatter = _frontmatter(PLUGIN / "agents" / "explore.md")
    assert "mcp__atelier__search" in frontmatter
    assert "mcp__atelier__read" in frontmatter
    assert "mcp__atelier__edit" in frontmatter
    assert "Agent" in frontmatter


def test_plugin_skills_are_packaged_locally() -> None:
    expected = {
        "analyze-failures",
        "benchmark",
        "check-plan",
        "context",
        "evals",
        "recall",
        "record-trace",
        "rescue",
        "savings",
        "settings",
        "share",
        "status",
        "task",
    }
    found = {path.parent.name for path in (PLUGIN / "skills").glob("*/SKILL.md")}
    assert expected <= found
