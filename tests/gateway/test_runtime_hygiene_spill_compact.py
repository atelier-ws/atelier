"""Runtime-hygiene gateway features: tool-output spill (T7), reversible
auto-compaction (T8), and the autonomous-compaction lever (T6).

T7 spilling is default-on and explicitly disableable; T8 auto-compaction remains
default-off. These exercise the spill store, the two dispatch helpers, and the
`compact` tool ops directly — deterministic, no network, no LLM.
"""

from __future__ import annotations

import os
import re
import time

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
    # T7 defaults ON; tests that exercise the off path disable it explicitly.
    monkeypatch.delenv("ATELIER_TOOL_OUTPUT_SPILL", raising=False)
    monkeypatch.delenv("ATELIER_MCP_SPILL_RESULT_CHARS", raising=False)
    monkeypatch.delenv("ATELIER_MCP_SPILL_MAX_FILES", raising=False)
    monkeypatch.delenv("ATELIER_MCP_SPILL_TTL_SECONDS", raising=False)
    monkeypatch.delenv("ATELIER_AUTO_COMPACT_OUTPUT", raising=False)


# --------------------------------------------------------------------------- #
# T7 — tool_output_spill store: spill + retrieve round-trip                     #
# --------------------------------------------------------------------------- #


def test_spill_then_retrieve_round_trips_full_content() -> None:
    payload = "HEAD" + ("x" * 50000) + "TAIL"
    record = tool_output_spill.spill(payload, tool_name="bash", kind="tool_output")
    assert record is not None
    assert record.ref_id.startswith(tool_output_spill.SPILL_REF_PREFIX)
    assert record.path.exists()

    got = tool_output_spill.retrieve(record.ref_id)
    assert got["content"] == payload  # nothing lost
    assert got["tool"] == "bash"
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


def test_spill_helper_noop_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "0")
    text = "z" * 200_000
    out = mcp_server._spill_oversized_result_text(text, "bash", {}, limit=1000)
    assert out == text  # flag off -> unchanged, legacy truncation still runs


def test_spill_helper_noop_for_unlisted_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    text = "z" * 200_000
    out = mcp_server._spill_oversized_result_text(text, "grep", {}, limit=1000)
    assert out == text  # grep is not a spill-worthy tool


def test_spill_helper_passes_through_small_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    text = "small enough"
    out = mcp_server._spill_oversized_result_text(text, "bash", {}, limit=1_000_000)
    assert out == text  # within budget -> nothing spilled


def test_spill_helper_spills_and_returns_recoverable_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    text = "HEAD-MARKER" + ("q" * 200_000) + "TAIL-MARKER"
    out = mcp_server._spill_oversized_result_text(text, "bash", {}, limit=64 * 1024)

    assert len(out) < len(text)  # host-facing text is a compact summary
    assert out.startswith("HEAD-MARKER")  # head preserved in summary
    assert "TAIL-MARKER" in out  # tail preserved in summary
    assert tool_output_spill.SPILL_REF_PREFIX in out  # ref id present
    assert "retrieve" in out  # recovery hint present

    # The hint must point at a ref that recovers the FULL original.
    recovered = tool_output_spill.retrieve(_extract_ref(out))
    assert recovered["content"] == text


def test_spill_helper_enforces_strict_char_cap_including_ref() -> None:
    text = "HEAD-MARKER" + ("q" * 200_000) + "TAIL-MARKER"
    out = mcp_server._spill_oversized_result_text(text, "bash", {}, limit=2048, unit="chars")

    assert len(out) <= 2048
    assert out.startswith("HEAD-MARKER")
    assert "TAIL-MARKER" in out
    recovered = tool_output_spill.retrieve(_extract_ref(out))
    assert recovered["content"] == text


def test_spill_result_chars_defaults_to_2k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_MCP_SPILL_RESULT_CHARS", raising=False)
    assert mcp_server._spill_result_chars() == 2048


def test_spill_result_chars_per_tool_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_MCP_SPILL_RESULT_CHARS", raising=False)
    # bash gets a larger inline budget; web_fetch/sql fall back to the 2 KiB default.
    assert mcp_server._spill_result_chars("bash") == 8 * 1024
    assert mcp_server._spill_result_chars("web_fetch") == 2048
    assert mcp_server._spill_result_chars("sql") == 2048


def test_spill_result_chars_env_overrides_all_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_SPILL_RESULT_CHARS", "1234")
    # An explicit env value wins for every tool, including the bash override.
    assert mcp_server._spill_result_chars("bash") == 1234
    assert mcp_server._spill_result_chars("web_fetch") == 1234
    assert mcp_server._spill_result_chars() == 1234


def test_spill_result_chars_env_zero_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_SPILL_RESULT_CHARS", "0")
    assert mcp_server._spill_result_chars("bash") == 0


def test_enforce_retention_caps_file_count(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_SPILL_MAX_FILES", "3")
    monkeypatch.setenv("ATELIER_MCP_SPILL_TTL_SECONDS", "0")  # isolate count-axis
    for i in range(6):
        p = tmp_path / f"tool_output-bash-{i}-{i:08x}.json"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (1000 + i, 1000 + i))  # strictly ascending mtime

    tool_output_spill._enforce_retention(tmp_path)

    assert len(list(tmp_path.glob("*.json"))) == 3
    # The three newest (i=3,4,5) survive; the three oldest are evicted.
    for i in (3, 4, 5):
        assert (tmp_path / f"tool_output-bash-{i}-{i:08x}.json").exists()
    for i in (0, 1, 2):
        assert not (tmp_path / f"tool_output-bash-{i}-{i:08x}.json").exists()


def test_enforce_retention_evicts_by_age(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_MCP_SPILL_MAX_FILES", raising=False)
    monkeypatch.setenv("ATELIER_MCP_SPILL_TTL_SECONDS", "100")
    now = time.time()
    old = tmp_path / "tool_output-bash-old.json"
    fresh = tmp_path / "tool_output-bash-fresh.json"
    old.write_text("{}", encoding="utf-8")
    os.utime(old, (now - 500, now - 500))
    fresh.write_text("{}", encoding="utf-8")
    os.utime(fresh, (now - 1, now - 1))

    tool_output_spill._enforce_retention(tmp_path)

    assert not old.exists()
    assert fresh.exists()


def test_enforce_retention_disabled_keeps_all(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATELIER_MCP_SPILL_MAX_FILES", "0")
    monkeypatch.setenv("ATELIER_MCP_SPILL_TTL_SECONDS", "0")
    for i in range(5):
        (tmp_path / f"tool_output-bash-{i}.json").write_text("{}", encoding="utf-8")

    tool_output_spill._enforce_retention(tmp_path)

    assert len(list(tmp_path.glob("*.json"))) == 5


def test_spill_bounded_and_leaves_no_temp(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cap to 2 then create 5 spills via the real spill() path (autouse spill dir).
    monkeypatch.setenv("ATELIER_MCP_SPILL_MAX_FILES", "2")
    monkeypatch.delenv("ATELIER_MCP_SPILL_TTL_SECONDS", raising=False)
    spill_dir = tool_output_spill._spill_dir()
    for i in range(5):
        assert tool_output_spill.spill(f"content-{i}", tool_name="bash") is not None

    # Directory stays bounded and the atomic write leaves no in-flight temp files.
    assert len(list(spill_dir.glob("*.json"))) <= 2
    assert list(spill_dir.glob("*.tmp")) == []


def test_retrieve_rejects_non_dict_envelope() -> None:
    # Valid JSON that isn't an object must yield a structured error, not an
    # uncaught AttributeError from envelope.get(...).
    spill_dir = tool_output_spill._spill_dir()
    (spill_dir / "tool_output-bad.json").write_text("[1, 2, 3]", encoding="utf-8")

    out = tool_output_spill.retrieve("spill:tool_output-bad.json")

    assert "error" in out
    assert out.get("ref_id") == "spill:tool_output-bad.json"
    assert "content" not in out


def test_summary_with_ref_preserves_ref_under_tiny_cap() -> None:
    # A cap below the full hint but above the bare ref id must keep the recovery
    # ref intact (never cut mid-ref) and honor the return bound, so the on-disk
    # spill is still recoverable.
    record = tool_output_spill.spill("x" * 5000, tool_name="bash")
    assert record is not None
    tiny = len(record.ref_id) + 5

    out = tool_output_spill.summary_with_ref("SUMMARY-TEXT", record, tool_name="bash", max_chars=tiny)

    assert len(out) <= tiny
    assert record.ref_id in out
    assert tool_output_spill.retrieve(out)["content"] == "x" * 5000


def test_spill_is_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATELIER_TOOL_OUTPUT_SPILL", raising=False)
    assert mcp_server._tool_output_spill_enabled() is True


def test_read_exempt_from_strict_char_cap() -> None:
    """`read` is the incremental retrieval surface (ranges, expand=true, slice
    windows) and the tool used to recover spilled output, so the 2 KiB char cap
    must NOT force-summarize it. It stays in _SPILL_TOOLS (multi-MB wire
    backstop) but is absent from the char-cap set the dispatcher passes.
    """
    assert "read" not in mcp_server._SPILL_CHAR_CAP_TOOLS
    assert "read" in mcp_server._SPILL_TOOLS

    text = "HEAD-MARKER" + ("q" * 200_000) + "TAIL-MARKER"
    out = mcp_server._spill_oversized_result_text(
        text, "read", {}, limit=2048, unit="chars", tools=mcp_server._SPILL_CHAR_CAP_TOOLS
    )
    assert out == text  # returned in full, not spilled


def test_shell_still_char_capped() -> None:
    """Primary target: shell/bash output above the cap is still spilled (full
    original recoverable)."""
    text = "x" * 200_000
    out = mcp_server._spill_oversized_result_text(
        text, "bash", {}, limit=2048, unit="chars", tools=mcp_server._SPILL_CHAR_CAP_TOOLS
    )
    assert len(out) <= 2048
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
    out = mcp_server._auto_compact_result_text(text, "bash", {})

    assert len(out) < len(text)  # compacted
    assert "auto-compacted" in out
    assert "ORIGINAL preserved" in out
    assert tool_output_spill.SPILL_REF_PREFIX in out

    recovered = tool_output_spill.retrieve(_extract_ref(out))
    assert recovered["content"] == text  # original fully recoverable
    assert recovered["kind"] == "original"


def test_auto_compact_code_is_ast_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    # The AST source-projection path is Pro; treat the install as licensed.
    monkeypatch.setattr("atelier.core.capabilities.licensing.feature_active", lambda *a, **k: True)
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
    out = mcp_server._spill_oversized_result_text(text, "bash", {}, 1000, unit="chars")
    assert len(out) < len(text)
    recovered = tool_output_spill.retrieve(_extract_ref(out))
    assert recovered["content"] == text  # FULL untransformed payload preserved


def test_handle_spills_full_untransformed_payload_before_compaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end through _handle: with the flag on and an oversized result, the
    spilled artifact must hold the FULL untransformed payload — specifically the
    MIDDLE that the legacy _compact_result_text would otherwise drop."""
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    # Char threshold well below the payload so the char-gated spill fires.
    monkeypatch.setenv("ATELIER_MCP_SPILL_RESULT_CHARS", "2048")

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
    assert len(host_text) <= 2048
    assert middle_marker not in host_text  # the middle is dropped from the summary
    # ...but the spilled ref recovers the FULL untransformed payload, middle and all.
    recovered = tool_output_spill.retrieve(_extract_ref(host_text))
    assert recovered["content"] == payload
    assert middle_marker in recovered["content"]


def test_handle_spill_flag_off_does_not_spill(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag-off behavior preserved: no spill ref, legacy char compaction applies."""
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "0")
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


def test_handle_passes_per_tool_char_cap_to_spill(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real _handle dispatch must pass the PER-TOOL char cap to the char-gated
    spill: bash -> 8 KiB, web_fetch -> 2 KiB (i.e. _spill_result_chars(name), not
    a single global cap). Guards against the call site dropping ``name``."""
    monkeypatch.setenv("ATELIER_TOOL_OUTPUT_SPILL", "1")
    monkeypatch.delenv("ATELIER_MCP_SPILL_RESULT_CHARS", raising=False)  # per-tool defaults

    seen: dict[str, int] = {}
    real = mcp_server._spill_oversized_result_text

    def _spy(
        text: str,
        tool_name: str,
        args: dict,  # type: ignore[type-arg]
        limit: int,
        *,
        unit: str = "bytes",
        tools: object = None,
    ) -> str:
        if unit == "chars":
            seen[tool_name] = limit
        if tools is None:
            return real(text, tool_name, args, limit, unit=unit)
        return real(text, tool_name, args, limit, unit=unit, tools=tools)  # type: ignore[arg-type]

    monkeypatch.setattr(mcp_server, "_spill_oversized_result_text", _spy)

    payload = "x" * 5000
    monkeypatch.setitem(mcp_server.TOOLS["web_fetch"], "handler", lambda _a: {"content": payload})
    monkeypatch.setitem(mcp_server.TOOLS["bash"], "handler", lambda _a: payload)

    for rid, tool, arguments in (
        (1, "web_fetch", {"url": "https://example.test"}),
        (2, "bash", {"command": "echo hi"}),
    ):
        mcp_server._handle(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )

    assert seen["web_fetch"] == 2048
    assert seen["bash"] == 8 * 1024
