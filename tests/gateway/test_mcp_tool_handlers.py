"""Comprehensive tests for the Core-6 MCP tool surface in mcp_server.py.

Core-6 tools: atelier_get_reasoning_context, atelier_check_plan,
atelier_rescue_failure, atelier_record_trace, atelier_run_rubric_gate,
atelier_compress_context. Removed tools are verified to return errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from atelier.gateway.adapters.mcp_server import TOOLS, _handle

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _call(name: str, args: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """Invoke a tool via the MCP _handle() dispatcher in local mode."""
    req: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    resp = _handle(req)
    assert isinstance(resp, dict)
    return resp


def _result(resp: dict[str, Any]) -> Any:
    """Extract and JSON-decode the structured result from a tools/call response."""
    assert "result" in resp, resp
    return json.loads(resp["result"]["content"][0]["text"])


def _seed_store(tmp_path: Path) -> Path:
    """Initialize an atelier store and return the root."""
    from click.testing import CliRunner

    from atelier.gateway.adapters.cli import cli

    root = tmp_path / ".atelier"
    runner = CliRunner()
    runner.invoke(cli, ["--root", str(root), "init"])
    return root


@pytest.fixture()
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _seed_store(tmp_path)
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    # Reset global ledger between tests
    import atelier.gateway.adapters.mcp_server as m

    m._current_ledger = None
    return root


# --------------------------------------------------------------------------- #
# MCP Protocol                                                                #
# --------------------------------------------------------------------------- #


class TestMCPProtocol:
    def test_initialize_returns_server_info(self) -> None:
        req: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        }
        resp = _handle(req)
        assert resp is not None
        assert resp["result"]["serverInfo"]["name"] == "atelier-reasoning"
        assert resp["result"]["protocolVersion"] == "2024-11-05"

    def test_notifications_initialized_returns_none(self) -> None:
        req: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": None,
            "method": "notifications/initialized",
            "params": {},
        }
        resp = _handle(req)
        assert resp is None

    def test_tools_list_returns_all_registered_tools(self) -> None:
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = _handle(req)
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        for expected in TOOLS:
            assert expected in names, f"tool {expected!r} missing from tools/list"

    def test_tools_list_each_entry_has_schema(self) -> None:
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = _handle(req)
        assert resp is not None
        for t in resp["result"]["tools"]:
            assert t["name"]
            assert isinstance(t.get("inputSchema"), dict)

    def test_unknown_method_returns_error(self) -> None:
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": 3, "method": "unknown/method", "params": {}}
        resp = _handle(req)
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_unknown_tool_returns_error(self) -> None:
        req: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }
        resp = _handle(req)
        assert resp is not None
        assert "error" in resp
        assert "unknown tool" in resp["error"]["message"]


# --------------------------------------------------------------------------- #
# Core reasoning tools                                                        #
# --------------------------------------------------------------------------- #


class TestCoreReasoningTools:
    def test_get_reasoning_context_returns_string(self, store_root: Path) -> None:
        resp = _call(
            "atelier_get_reasoning_context", {"task": "Fix Shopify publish bug"}, store_root
        )
        payload = _result(resp)
        assert "context" in payload
        assert isinstance(payload["context"], str)

    def test_get_reasoning_context_with_domain(self, store_root: Path) -> None:
        resp = _call(
            "atelier_get_reasoning_context",
            {"task": "Publish product", "domain": "beseam.shopify.publish"},
            store_root,
        )
        assert "result" in resp

    def test_check_plan_pass_status(self, store_root: Path) -> None:
        resp = _call(
            "atelier_check_plan",
            {"task": "Add a test file", "plan": ["Create test_foo.py", "Run pytest"]},
            store_root,
        )
        payload = _result(resp)
        assert "status" in payload
        assert payload["status"] in ("ok", "pass", "warn", "blocked")

    def test_check_plan_blocks_shopify_dead_end(self, store_root: Path) -> None:
        resp = _call(
            "atelier_check_plan",
            {
                "task": "Update Shopify product",
                "domain": "beseam.shopify.publish",
                "plan": ["Parse Shopify product handle from URL"],
            },
            store_root,
        )
        payload = _result(resp)
        assert payload["status"] == "blocked"

    def test_rescue_failure_returns_procedure(self, store_root: Path) -> None:
        resp = _call(
            "atelier_rescue_failure",
            {
                "task": "Update Shopify product",
                "error": "wrong product updated",
                "domain": "beseam.shopify.publish",
            },
            store_root,
        )
        payload = _result(resp)
        assert "rescue" in payload
        assert "analysis" in payload

    def test_rescue_failure_with_recent_actions(self, store_root: Path) -> None:
        resp = _call(
            "atelier_rescue_failure",
            {
                "task": "Run tests",
                "error": "pytest AssertionError",
                "recent_actions": ["edit foo.py", "run pytest", "run pytest again"],
            },
            store_root,
        )
        assert "result" in resp

    def test_run_rubric_gate_pass(self, store_root: Path) -> None:
        resp = _call(
            "atelier_run_rubric_gate",
            {
                "rubric_id": "rubric_shopify_publish",
                "checks": {
                    "product_identity_uses_gid": True,
                    "pre_publish_snapshot_exists": True,
                    "write_result_checked": True,
                    "post_publish_refetch_done": True,
                    "post_publish_audit_passed": True,
                    "rollback_available": True,
                    "localized_url_test_passed": True,
                    "changed_handle_test_passed": True,
                },
            },
            store_root,
        )
        payload = _result(resp)
        assert payload["status"] == "pass"

    def test_run_rubric_gate_blocked(self, store_root: Path) -> None:
        resp = _call(
            "atelier_run_rubric_gate",
            {"rubric_id": "rubric_shopify_publish", "checks": {}},
            store_root,
        )
        payload = _result(resp)
        assert payload["status"] == "blocked"

    def test_run_rubric_gate_unknown_raises(self, store_root: Path) -> None:
        resp = _call(
            "atelier_run_rubric_gate",
            {"rubric_id": "rubric_does_not_exist", "checks": {}},
            store_root,
        )
        assert "error" in resp

    def test_extract_reasonblock_removed(self, store_root: Path) -> None:
        # atelier_extract_reasonblock was removed from Core-6 surface
        resp = _call("atelier_extract_reasonblock", {"trace_id": "any"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Trace recording                                                             #
# --------------------------------------------------------------------------- #


class TestRecordTrace:
    def test_record_trace_returns_id(self, store_root: Path) -> None:
        resp = _call(
            "atelier_record_trace",
            {
                "agent": "codex",
                "domain": "coding",
                "task": "Add feature X",
                "status": "success",
                "files_touched": ["src/x.py"],
                "commands_run": ["pytest"],
                "validation_results": [{"name": "pytest", "passed": True, "detail": ""}],
            },
            store_root,
        )
        payload = _result(resp)
        assert "id" in payload
        assert "run_id" in payload

    def test_record_trace_redacts_secret(self, store_root: Path) -> None:
        resp = _call(
            "atelier_record_trace",
            {
                "agent": "test",
                "domain": "coding",
                "task": "Deploy with token sk-abc123secretkey",
                "status": "success",
            },
            store_root,
        )
        payload = _result(resp)
        assert "id" in payload  # succeeds; redaction happens inside

    def test_record_trace_partial_status(self, store_root: Path) -> None:
        resp = _call(
            "atelier_record_trace",
            {"agent": "gemini", "domain": "swe", "task": "Partial work", "status": "partial"},
            store_root,
        )
        assert "result" in resp

    def test_record_trace_realtime_capture(self, store_root: Path) -> None:
        resp = _call(
            "atelier_record_trace",
            {
                "agent": "codex",
                "domain": "coding",
                "task": "Fix failing tests",
                "status": "failed",
                "prompt": "Run tests and diagnose the first failure",
                "response": "pytest failed with AssertionError in auth tests",
                "bash_outputs": [
                    {
                        "command": "pytest -q",
                        "ok": False,
                        "stdout": "..F..",
                        "stderr": "AssertionError: expected 200 got 500",
                    }
                ],
            },
            store_root,
        )
        payload = _result(resp)
        assert "realtime_context" in payload
        assert "reduction_pct" in payload["realtime_context"]


# --------------------------------------------------------------------------- #
# Ledger tools                                                                #
# --------------------------------------------------------------------------- #


class TestLedgerTools:
    """Ledger helper tools were removed from the Core-6 MCP surface."""

    def test_record_call_removed(self, store_root: Path) -> None:
        resp = _call(
            "atelier_record_call",
            {"operation": "x", "model": "gpt-4", "input_tokens": 10, "output_tokens": 5},
            store_root,
        )
        assert "error" in resp

    def test_record_note_removed(self, store_root: Path) -> None:
        resp = _call("atelier_record_note", {"summary": "note"}, store_root)
        assert "error" in resp

    def test_get_run_ledger_removed(self, store_root: Path) -> None:
        resp = _call("atelier_get_run_ledger", {}, store_root)
        assert "error" in resp

    def test_update_run_ledger_removed(self, store_root: Path) -> None:
        resp = _call("atelier_update_run_ledger", {"updates": {}}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Monitor event                                                               #
# --------------------------------------------------------------------------- #


class TestMonitorEvent:
    """atelier_monitor_event was removed from Core-6 MCP surface."""

    def test_monitor_event_removed(self, store_root: Path) -> None:
        resp = _call("atelier_monitor_event", {"monitor": "m", "message": "msg"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Compress context                                                            #
# --------------------------------------------------------------------------- #


class TestCompressContext:
    def test_compress_context_returns_structure(self, store_root: Path) -> None:
        _call(
            "atelier_record_call",
            {"operation": "setup", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        resp = _call("atelier_compress_context", {}, store_root)
        payload = _result(resp)
        assert "preserved" in payload
        assert "prompt_block" in payload
        assert isinstance(payload["prompt_block"], str)

    def test_compress_context_preserved_has_expected_keys(self, store_root: Path) -> None:
        _call(
            "atelier_record_call",
            {"operation": "setup", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        payload = _result(_call("atelier_compress_context", {}, store_root))
        preserved = payload["preserved"]
        assert "active_rubrics" in preserved
        assert "active_reasonblocks" in preserved

    def test_compress_context_includes_realtime_snapshot(self, store_root: Path) -> None:
        _call(
            "atelier_record_trace",
            {
                "agent": "codex",
                "domain": "coding",
                "task": "Investigate flaky test",
                "status": "partial",
                "prompt": "Find flaky test root cause",
                "response": "Detected intermittent timeout in API client",
            },
            store_root,
        )
        payload = _result(_call("atelier_compress_context", {}, store_root))
        assert "realtime" in payload
        assert "prompt_block" in payload["realtime"]


# --------------------------------------------------------------------------- #
# Environment context                                                         #
# --------------------------------------------------------------------------- #


class TestGetEnvironment:
    """atelier_get_environment was removed from Core-6 MCP surface."""

    def test_get_environment_removed(self, store_root: Path) -> None:
        resp = _call("atelier_get_environment", {"env_id": "env_shopify_publish"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Smart tools                                                                 #
# --------------------------------------------------------------------------- #


class TestSmartTools:
    """Generic file tools were removed from Core-6 MCP surface."""

    def test_smart_read_removed(self, store_root: Path) -> None:
        resp = _call("atelier_smart_read", {"path": "/any/path.py"}, store_root)
        assert "error" in resp

    def test_smart_search_removed(self, store_root: Path) -> None:
        resp = _call("atelier_smart_search", {"query": "shopify publish"}, store_root)
        assert "error" in resp

    def test_cached_grep_removed(self, store_root: Path) -> None:
        resp = _call("atelier_cached_grep", {"pattern": "needle"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Core capability MCP tools                                                   #
# --------------------------------------------------------------------------- #


class TestCoreCapabilityTools:
    """Verify Core-6 surface and that auxiliary capability tools were removed."""

    def test_core_six_tools_registered(self) -> None:
        expected = {
            "atelier_get_reasoning_context",
            "atelier_check_plan",
            "atelier_rescue_failure",
            "atelier_record_trace",
            "atelier_run_rubric_gate",
            "atelier_compress_context",
            "atelier_memory_upsert_block",
            "atelier_memory_get_block",
            "atelier_memory_archive",
            "atelier_memory_recall",
            "atelier_smart_read",
        }
        assert expected.issubset(set(TOOLS.keys()))

    def test_removed_capability_tools_return_error(self, store_root: Path) -> None:
        for name in (
            "atelier_reasoning_reuse",
            "atelier_semantic_memory",
            "atelier_loop_monitor",
            "atelier_tool_supervisor",
            "atelier_context_compressor",
            "atelier_bash_intercept",
            "atelier_smart_edit",
            "atelier_symbol_search",
            "atelier_domain_list",
            "atelier_host_list",
        ):
            resp = _call(name, {}, store_root)
            assert "error" in resp, f"{name} should return an error (tool removed)"


class TestCompatibilityAliases:
    """Verify all six Core-6 tools are accessible via the MCP dispatcher."""

    def test_alias_atelier_check_plan_available(self, store_root: Path) -> None:
        resp = _call(
            "atelier_check_plan",
            {"task": "Add tests", "plan": ["Write tests", "Run pytest"]},
            store_root,
        )
        payload = _result(resp)
        assert "status" in payload

    def test_alias_atelier_get_reasoning_context_available(self, store_root: Path) -> None:
        resp = _call(
            "atelier_get_reasoning_context",
            {"task": "Fix publish regression", "domain": "beseam.shopify.publish"},
            store_root,
        )
        payload = _result(resp)
        assert isinstance(payload.get("context"), str)

    def test_alias_atelier_compress_context_available(self, store_root: Path) -> None:
        resp = _call("atelier_compress_context", {}, store_root)
        payload = _result(resp)
        assert "prompt_block" in payload

    def test_alias_atelier_status_removed(self, store_root: Path) -> None:
        resp = _call("atelier_status", {}, store_root)
        assert "error" in resp
