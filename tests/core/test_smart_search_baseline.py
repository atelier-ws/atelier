from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.tool_supervision.smart_search import (
    _CLAUDE_READ_LINE_LIMIT,
    _naive_bytes_for_matches,
)


def test_smart_search_chunk_baseline_is_claude_grep_paths(tmp_path: Path) -> None:
    path = tmp_path / "large.py"
    path.write_text("\n".join(f"line_{idx} = 'needle'" for idx in range(5000)), encoding="utf-8")

    matches = [{"path": str(path), "snippets": [{"text": "needle"}]}]

    assert _naive_bytes_for_matches(matches, mode="chunks") == len(str(path))
    assert _naive_bytes_for_matches(matches, mode="chunks") < path.stat().st_size


def test_smart_search_full_baseline_caps_claude_read_output(tmp_path: Path) -> None:
    path = tmp_path / "huge.py"
    lines = [f"line_{idx} = 'needle'" for idx in range(_CLAUDE_READ_LINE_LIMIT + 500)]
    path.write_text("\n".join(lines), encoding="utf-8")

    baseline = _naive_bytes_for_matches([{"path": str(path)}], mode="full")
    full_size = path.stat().st_size

    assert baseline < full_size
    assert baseline == len("\n".join(lines[:_CLAUDE_READ_LINE_LIMIT]))
