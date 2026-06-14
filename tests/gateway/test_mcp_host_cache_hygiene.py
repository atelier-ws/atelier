"""Host-mode cache-hygiene + result-bounding tests for the MCP dispatch path.

When Atelier is a guest MCP server inside a host agent (Claude Code / Codex), the
host re-sends the whole conversation each turn, so Atelier's tool schemas and
tool results ride in the host's cached prompt. These cover the two levers Atelier
actually controls there: deterministic ordering (so the prefix cache stays warm)
and tail-preserving compaction of runaway results.
"""

from __future__ import annotations

import pytest

from atelier.gateway.adapters import mcp_server


def test_compact_result_text_passes_small_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_MCP_COMPACT_RESULT_CHARS", raising=False)
    small = "hello world"
    assert mcp_server._compact_result_text(small, "read") == small


def test_compact_result_text_compacts_oversized_keeping_head_and_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "1000")
    text = "HEAD" + ("m" * 20000) + "TAIL"
    out = mcp_server._compact_result_text(text, "shell")
    assert len(out) < len(text)
    assert out.startswith("HEAD")  # head preserved
    assert "TAIL" in out  # tail preserved -- the win over head-only truncation
    assert "truncated" in out  # omission marker from compress_tool_output
    assert "compacted from" in out  # recovery hint


def test_compact_result_text_disabled_with_env_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "0")
    text = "z" * 50000
    assert mcp_server._compact_result_text(text, "read") == text


def test_compact_result_text_invalid_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "not-an-int")
    # default is 256 KiB; a sub-threshold payload passes through unchanged
    text = "a" * 1000
    assert mcp_server._compact_result_text(text, "grep") == text


def test_tools_list_is_sorted_by_name() -> None:
    resp = mcp_server._handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert resp is not None
    names = [tool["name"] for tool in resp["result"]["tools"]]
    assert names == sorted(names)
