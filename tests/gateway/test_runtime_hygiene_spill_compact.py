"""Runtime-hygiene gateway features: tool-output spill (T7), reversible
auto-compaction (T8), and the autonomous-compaction lever (T6).

Each feature is behind a default-OFF env flag; with the flag off the dispatch
path must behave byte-for-byte as before. These exercise the spill store, the
two dispatch helpers, and the `compact` tool ops directly — deterministic, no
network, no LLM.
"""

from __future__ import annotations

import re

import pytest

from atelier.core.capabilities.tool_supervision import tool_output_spill
from atelier.gateway.adapters import mcp_server

_REF_RE = re.compile(r"(spill:[^\s\"';\]]+?\.json)")


def _extract_ref(text: str) -> str:
    """Pull the first spill ref id out of a host-facing summary string."""
    match = _REF_RE.search(text)
    assert match is not None, f"no spill ref in: {text[-200:]!r}"
    return match.group(1)


@pytest.fixture(autouse=True)
def _isolated_spill_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_SPILL_DIR", str(tmp_path / "spill"))
    # Default both feature flags OFF for every test unless it opts in.
    monkeypatch.delenv("ATELIER_TOOL_OUTPUT_SPILL", raising=False)
    monkeypatch.delenv("ATELIER_AUTO_COMPACT_OUTPUT", raising=False)


# --------------------------------------------------------------------------- #
# T7 — tool_output_spill store: spill + retrieve round-trip                     #
# --------------------------------------------------------------------------- #


def test_spill_then_retrieve_round_trips_full_content() -> None:
    payload = "HEAD" + ("x" * 50000) + "TAIL"
    record = tool_output_spill.spill(payload, tool_name="shell", kind="tool_output")
    assert record is not None
    assert record.ref_id.startswith(tool_output_spill.SPILL_REF_PREFIX)
    assert record.path.exists()

    got = tool_output_spill.retrieve(record.ref_id)
    assert got["content"] == payload  # nothing lost
    assert got["tool"] == "shell"
    assert got["total_chars"] == len(payload)
    assert "error" not in got


def test_retrieve_supports_slice_window() -> None:
    payload = "".join(str(i % 10) for i in range(1000))
    record = tool_output_spill.spill(payload, tool_name="read")
    assert record is not None
    got = tool_output_spill.retrieve(record.ref_id, slice=(100, 50))
    assert got["content"] == payload[100:150]
    assert got["slice"] == {"start": 100, "end": 150, "total_chars": 1000}


def test_retrieve_unknown_ref_returns_error_not_raise() -> None:
    got = tool_output_spill.retrieve("spill:does-not-exist.json")
    assert "error" in got


def test_retrieve_rejects_path_traversal() -> None:
    got = tool_output_spill.retrieve("spill:../../etc/passwd")
    assert "error" in got
    assert "invalid" in got["error"]


# --------------------------------------------------------------------------- #
# T7 — dispatch helper: _spill_oversized_result_text                            #
# --------------------------------------------------------------------------- #


def test_spill_helper_noop_when_flag_off() -> None:
    text = "z" * 200_000
    out = mcp_server._spill_oversized_result_text(text, "shell", {}, limit=1000)
    assert out == text  # flag off -> unchanged, legacy truncation still runs


def test_spill_helper_noop_for_unlisted_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    text = "z" * 200_000
    out = mcp_server._spill_oversized_result_text(text, "grep", {}, limit=1000)
    assert out == text  # grep is not a spill-worthy tool


def test_spill_helper_passes_through_small_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    text = "small enough"
    out = mcp_server._spill_oversized_result_text(text, "shell", {}, limit=1_000_000)
    assert out == text  # within budget -> nothing spilled


def test_spill_helper_spills_and_returns_recoverable_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    text = "HEAD-MARKER" + ("q" * 200_000) + "TAIL-MARKER"
    out = mcp_server._spill_oversized_result_text(text, "shell", {}, limit=64 * 1024)

    assert len(out) < len(text)  # host-facing text is a compact summary
    assert out.startswith("HEAD-MARKER")  # head preserved in summary
    assert "TAIL-MARKER" in out  # tail preserved in summary
    assert tool_output_spill.SPILL_REF_PREFIX in out  # ref id present
    assert "retrieve" in out  # recovery hint present

    # The hint must point at a ref that recovers the FULL original.
    recovered = tool_output_spill.retrieve(_extract_ref(out))
    assert recovered["content"] == text


# --------------------------------------------------------------------------- #
# T8 — reversible auto-compaction: _auto_compact_result_text                    #
# --------------------------------------------------------------------------- #


def test_auto_compact_noop_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "1000")
    text = "a" * 50_000
    out = mcp_server._auto_compact_result_text(text, "read", {"path": "x.txt"})
    assert out == text  # flag off -> byte-identical to prior behavior


def test_auto_compact_passes_through_small_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_AUTO_COMPACT_OUTPUT", "1")
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "100000")
    text = "a" * 1000
    out = mcp_server._auto_compact_result_text(text, "read", {"path": "x.txt"})
    assert out == text  # under threshold -> untouched


def test_auto_compact_is_reversible_via_spill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_AUTO_COMPACT_OUTPUT", "1")
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "2000")
    # Non-code tool -> deterministic compact_output path.
    text = "START" + ("data line\n" * 5000) + "END"
    out = mcp_server._auto_compact_result_text(text, "shell", {})

    assert len(out) < len(text)  # compacted
    assert "auto-compacted" in out
    assert "ORIGINAL preserved" in out
    assert tool_output_spill.SPILL_REF_PREFIX in out

    recovered = tool_output_spill.retrieve(_extract_ref(out))
    assert recovered["content"] == text  # original fully recoverable
    assert recovered["kind"] == "original"


def test_auto_compact_code_is_ast_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_AUTO_COMPACT_OUTPUT", "1")
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "2000")
    # Python source with lots of blank lines -> source_projection compact applies.
    src = "def f():\n" + "\n\n\n".join(f"    x{i} = {i}  " for i in range(2000)) + "\n"
    out = mcp_server._auto_compact_result_text(src, "read", {"path": "mod.py"})
    assert "source_projection:python" in out  # AST/structure-aware method tag
    assert tool_output_spill.SPILL_REF_PREFIX in out  # still reversible


# --------------------------------------------------------------------------- #
# T6 — autonomous-compaction lever + retrieve op on the `compact` tool          #
# --------------------------------------------------------------------------- #


def test_compact_tool_default_op_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake(session_id=None):  # type: ignore[no-untyped-def]
        captured["session_id"] = session_id
        return {"prompt_block": "BLOCK", "tokens_freed": 42}

    monkeypatch.setattr(mcp_server, "_compress_context", _fake)
    out = mcp_server.tool_compact({})  # default op="compact"
    assert out == {"prompt_block": "BLOCK", "tokens_freed": 42}
    assert "op" not in out  # default op adds no marker


def test_compact_tool_consolidate_reuses_compaction_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def _fake(session_id=None):  # type: ignore[no-untyped-def]
        calls.append(session_id)
        return {"prompt_block": "BLOCK", "tokens_freed": 7}

    monkeypatch.setattr(mcp_server, "_compress_context", _fake)
    out = mcp_server.tool_compact({"op": "consolidate", "session_id": "sess-1"})
    assert calls == ["sess-1"]  # reused the existing entrypoint exactly once
    assert out["op"] == "consolidate"
    assert out["tokens_freed"] == 7


def test_compact_tool_retrieve_op_reads_spill() -> None:
    record = tool_output_spill.spill("PAYLOAD-CONTENT", tool_name="sql")
    assert record is not None
    out = mcp_server.tool_compact({"op": "retrieve", "ref_id": record.ref_id})
    assert out["content"] == "PAYLOAD-CONTENT"


def test_compact_tool_retrieve_op_windows_with_slice() -> None:
    record = tool_output_spill.spill("0123456789", tool_name="sql")
    assert record is not None
    out = mcp_server.tool_compact({"op": "retrieve", "ref_id": record.ref_id, "slice_start": 2, "slice_length": 3})
    assert out["content"] == "234"


def test_compact_tool_retrieve_op_requires_ref_id() -> None:
    out = mcp_server.tool_compact({"op": "retrieve"})
    assert "error" in out


# --------------------------------------------------------------------------- #
# M1 — spill fires at the CHAR threshold, BEFORE legacy char compaction, so the #
# spilled artifact holds the FULL untransformed payload (not compacted text).   #
# --------------------------------------------------------------------------- #


def test_spill_helper_char_unit_fires_at_char_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    # Under default byte caps (6MB) this 200K-char payload would NOT spill, but
    # the char-gated call (threshold 1000 chars) must.
    text = "HEAD" + ("m" * 200_000) + "TAIL"
    out = mcp_server._spill_oversized_result_text(text, "shell", {}, 1000, unit="chars")
    assert len(out) < len(text)
    recovered = tool_output_spill.retrieve(_extract_ref(out))
    assert recovered["content"] == text  # FULL untransformed payload preserved


def test_handle_spills_full_untransformed_payload_before_compaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end through _handle: with the flag on and an oversized result, the
    spilled artifact must hold the FULL untransformed payload — specifically the
    MIDDLE that the legacy _compact_result_text would otherwise drop."""
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    # Char threshold well below the payload so the char-gated spill fires.
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "2000")

    # web_fetch renders its result as the raw `content` string (no transform),
    # and is a spill-worthy tool, so it isolates the dispatch ordering cleanly.
    middle_marker = "UNIQUE-MIDDLE-MARKER-THAT-COMPACTION-WOULD-DROP"
    payload = "HEAD" + ("a" * 100_000) + middle_marker + ("b" * 100_000) + "TAIL"

    def _fake_web_fetch(_args: dict) -> dict:  # type: ignore[type-arg]
        return {"content": payload}

    monkeypatch.setitem(mcp_server.TOOLS["web_fetch"], "handler", _fake_web_fetch)

    resp = mcp_server._handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "web_fetch", "arguments": {"url": "https://example.test"}},
        }
    )
    assert resp is not None
    host_text = resp["result"]["content"][0]["text"]
    # Host-facing text is a compact summary that fits the budget...
    assert len(host_text) < len(payload)
    assert middle_marker not in host_text  # the middle is dropped from the summary
    # ...but the spilled ref recovers the FULL untransformed payload, middle and all.
    recovered = tool_output_spill.retrieve(_extract_ref(host_text))
    assert recovered["content"] == payload
    assert middle_marker in recovered["content"]


def test_handle_spill_flag_off_does_not_spill(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag-off behavior preserved: no spill ref, legacy char compaction applies."""
    monkeypatch.delenv("ATELIER_TOOL_OUTPUT_SPILL", raising=False)
    monkeypatch.setenv("ATELIER_MCP_COMPACT_RESULT_CHARS", "2000")
    payload = "HEAD" + ("a" * 200_000) + "TAIL"

    def _fake_web_fetch(_args: dict) -> dict:  # type: ignore[type-arg]
        return {"content": payload}

    monkeypatch.setitem(mcp_server.TOOLS["web_fetch"], "handler", _fake_web_fetch)
    resp = mcp_server._handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "web_fetch", "arguments": {"url": "https://example.test"}},
        }
    )
    assert resp is not None
    host_text = resp["result"]["content"][0]["text"]
    assert tool_output_spill.SPILL_REF_PREFIX not in host_text  # flag off -> no spill
    # Legacy char compaction still ran (its recovery hint, not a spill ref).
    assert "compacted" in host_text
