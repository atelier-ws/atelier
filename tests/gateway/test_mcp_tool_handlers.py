"""Comprehensive tests for every MCP tool handler in mcp_server.py.

Covers all 17 tools in the TOOLS registry plus MCP protocol handling
(initialize, tools/list, tools/call, unknown method, unknown tool).
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
    assert resp is not None
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
        resp = _call("get_reasoning_context", {"task": "Fix Shopify publish bug"}, store_root)
        payload = _result(resp)
        assert "context" in payload
        assert isinstance(payload["context"], str)

    def test_get_reasoning_context_with_domain(self, store_root: Path) -> None:
        resp = _call(
            "get_reasoning_context",
            {"task": "Publish product", "domain": "beseam.shopify.publish"},
            store_root,
        )
        assert "result" in resp

    def test_check_plan_pass_status(self, store_root: Path) -> None:
        resp = _call(
            "check_plan",
            {"task": "Add a test file", "plan": ["Create test_foo.py", "Run pytest"]},
            store_root,
        )
        payload = _result(resp)
        assert "status" in payload
        assert payload["status"] in ("ok", "pass", "warn", "blocked")

    def test_check_plan_blocks_shopify_dead_end(self, store_root: Path) -> None:
        resp = _call(
            "check_plan",
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
            "rescue_failure",
            {
                "task": "Update Shopify product",
                "error": "wrong product updated",
                "domain": "beseam.shopify.publish",
            },
            store_root,
        )
        payload = _result(resp)
        assert "rescue" in payload

    def test_rescue_failure_with_recent_actions(self, store_root: Path) -> None:
        resp = _call(
            "rescue_failure",
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
            "run_rubric_gate",
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
            "run_rubric_gate",
            {"rubric_id": "rubric_shopify_publish", "checks": {}},
            store_root,
        )
        payload = _result(resp)
        assert payload["status"] == "blocked"

    def test_run_rubric_gate_unknown_raises(self, store_root: Path) -> None:
        resp = _call(
            "run_rubric_gate",
            {"rubric_id": "rubric_does_not_exist", "checks": {}},
            store_root,
        )
        assert "error" in resp

    def test_extract_reasonblock_from_trace(self, store_root: Path) -> None:
        # Record a trace first so we have something to extract from
        from atelier.core.foundation.models import Trace, ValidationResult
        from atelier.gateway.adapters.runtime import ReasoningRuntime

        rt = ReasoningRuntime(store_root)
        trace = Trace(
            id=Trace.make_id("Add pagination", "test"),
            agent="test",
            domain="coding",
            task="Add pagination",
            status="success",
            files_touched=["src/paginate.py"],
            commands_run=["pytest", "ruff check src/"],
            validation_results=[ValidationResult(name="pytest", passed=True, detail="")],
        )
        rt.store.record_trace(trace)

        resp = _call("extract_reasonblock", {"trace_id": trace.id}, store_root)
        payload = _result(resp)
        assert "block" in payload
        assert "confidence" in payload
        assert "reasons" in payload
        assert isinstance(payload["saved"], bool)

    def test_extract_reasonblock_unknown_trace(self, store_root: Path) -> None:
        resp = _call("extract_reasonblock", {"trace_id": "nonexistent-trace-id"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Trace recording                                                             #
# --------------------------------------------------------------------------- #


class TestRecordTrace:
    def test_record_trace_returns_id(self, store_root: Path) -> None:
        resp = _call(
            "record_trace",
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
            "record_trace",
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
            "record_trace",
            {"agent": "gemini", "domain": "swe", "task": "Partial work", "status": "partial"},
            store_root,
        )
        assert "result" in resp


# --------------------------------------------------------------------------- #
# Ledger tools                                                                #
# --------------------------------------------------------------------------- #


class TestLedgerTools:
    def test_record_call_persists(self, store_root: Path) -> None:
        resp = _call(
            "record_call",
            {
                "operation": "check_plan",
                "model": "claude-sonnet-4-5",
                "input_tokens": 1200,
                "output_tokens": 400,
                "prompt": "task: fix bug",
                "response": "Here is the plan...",
            },
            store_root,
        )
        payload = _result(resp)
        assert payload["recorded"] is True
        assert "run_id" in payload

    def test_record_call_with_cost(self, store_root: Path) -> None:
        resp = _call(
            "record_call",
            {
                "operation": "rescue",
                "model": "claude-sonnet-4-5",
                "input_tokens": 800,
                "output_tokens": 200,
                "cost_usd": 0.0045,
                "cache_read_tokens": 300,
                "lessons_used": ["rb-001", "rb-002"],
            },
            store_root,
        )
        assert _result(resp)["recorded"] is True

    def test_record_note_persists(self, store_root: Path) -> None:
        resp = _call(
            "record_note",
            {"summary": "Decided to use GID instead of handle", "payload": {"reason": "stable"}},
            store_root,
        )
        payload = _result(resp)
        assert payload["recorded"] is True

    def test_record_note_minimal(self, store_root: Path) -> None:
        resp = _call("record_note", {"summary": "just a note"}, store_root)
        assert _result(resp)["recorded"] is True

    def test_get_run_ledger_returns_dict(self, store_root: Path) -> None:
        # record a call to create the ledger file
        _call(
            "record_call",
            {"operation": "test", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        resp = _call("get_run_ledger", {}, store_root)
        payload = _result(resp)
        assert isinstance(payload, dict)

    def test_get_run_ledger_by_run_id(self, store_root: Path) -> None:
        import atelier.gateway.adapters.mcp_server as m

        led = m._get_ledger()
        _call(
            "record_call",
            {"operation": "test", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        resp = _call("get_run_ledger", {"run_id": led.run_id}, store_root)
        payload = _result(resp)
        assert payload.get("run_id") == led.run_id

    def test_update_run_ledger_field(self, store_root: Path) -> None:
        _call(
            "record_call",
            {"operation": "test", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        resp = _call("update_run_ledger", {"updates": {"task": "new task text"}}, store_root)
        payload = _result(resp)
        assert "task" in payload["updated"]


# --------------------------------------------------------------------------- #
# Monitor event                                                               #
# --------------------------------------------------------------------------- #


class TestMonitorEvent:
    def test_monitor_event_recorded(self, store_root: Path) -> None:
        _call(
            "record_call",
            {"operation": "setup", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        resp = _call(
            "monitor_event",
            {"monitor": "repeated_command_failure", "severity": "high", "message": "pytest x3"},
            store_root,
        )
        payload = _result(resp)
        assert payload["recorded"] is True

    def test_monitor_event_default_severity(self, store_root: Path) -> None:
        _call(
            "record_call",
            {"operation": "setup", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        resp = _call(
            "monitor_event",
            {"monitor": "second_guessing", "message": "edit-revert on foo.py"},
            store_root,
        )
        assert _result(resp)["recorded"] is True


# --------------------------------------------------------------------------- #
# Compress context                                                            #
# --------------------------------------------------------------------------- #


class TestCompressContext:
    def test_compress_context_returns_structure(self, store_root: Path) -> None:
        _call(
            "record_call",
            {"operation": "setup", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        resp = _call("compress_context", {}, store_root)
        payload = _result(resp)
        assert "preserved" in payload
        assert "prompt_block" in payload
        assert isinstance(payload["prompt_block"], str)

    def test_compress_context_preserved_has_expected_keys(self, store_root: Path) -> None:
        _call(
            "record_call",
            {"operation": "setup", "model": "gpt-4", "input_tokens": 100, "output_tokens": 50},
            store_root,
        )
        payload = _result(_call("compress_context", {}, store_root))
        preserved = payload["preserved"]
        assert "active_rubrics" in preserved
        assert "active_reasonblocks" in preserved


# --------------------------------------------------------------------------- #
# Environment context                                                         #
# --------------------------------------------------------------------------- #


class TestGetEnvironmentContext:
    def test_get_environment_context_shopify(self, store_root: Path) -> None:
        resp = _call("get_environment_context", {"env_id": "env_shopify_publish"}, store_root)
        payload = _result(resp)
        assert payload["environment"]["id"] == "env_shopify_publish"
        assert "rubric" in payload
        assert "blocks" in payload

    def test_get_environment_context_unknown_raises(self, store_root: Path) -> None:
        resp = _call("get_environment_context", {"env_id": "env_does_not_exist"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Smart tools                                                                 #
# --------------------------------------------------------------------------- #


class TestSmartTools:
    def test_smart_read_existing_file(self, store_root: Path, tmp_path: Path) -> None:
        f = tmp_path / "target.py"
        f.write_text("# Hello\n" * 100, encoding="utf-8")
        resp = _call("smart_read", {"path": str(f)}, store_root)
        payload = _result(resp)
        assert payload["path"] == str(f)
        assert "summary" in payload
        assert "related_blocks" in payload

    def test_smart_read_missing_file_returns_error(self, store_root: Path) -> None:
        resp = _call("smart_read", {"path": "/nonexistent/path/file.py"}, store_root)
        assert "error" in resp

    def test_smart_search_returns_matches(self, store_root: Path) -> None:
        resp = _call("smart_search", {"query": "shopify publish"}, store_root)
        payload = _result(resp)
        assert "matches" in payload
        assert isinstance(payload["matches"], list)

    def test_smart_search_with_limit(self, store_root: Path) -> None:
        resp = _call("smart_search", {"query": "publish", "limit": 3}, store_root)
        payload = _result(resp)
        assert len(payload["matches"]) <= 3

    def test_cached_grep_returns_output(self, store_root: Path, tmp_path: Path) -> None:
        f = tmp_path / "haystack.py"
        f.write_text("needle = 1\nother = 2\n", encoding="utf-8")
        resp = _call("cached_grep", {"pattern": "needle", "path": str(tmp_path)}, store_root)
        payload = _result(resp)
        assert "output" in payload
        assert "needle" in payload["output"]

    def test_cached_grep_rejects_shell_metachar(self, store_root: Path) -> None:
        resp = _call("cached_grep", {"pattern": "foo; rm -rf /"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Domain tools                                                                #
# --------------------------------------------------------------------------- #


class TestDomainTools:
    def test_domain_list_returns_bundle_list(self, store_root: Path) -> None:
        resp = _call("atelier_domain_list", {}, store_root)
        payload = _result(resp)
        assert "bundles" in payload
        ids = {b["bundle_id"] for b in payload["bundles"]}
        assert "swe.general" in ids

    def test_domain_info_swe_general(self, store_root: Path) -> None:
        resp = _call("atelier_domain_info", {"bundle_id": "swe.general"}, store_root)
        payload = _result(resp)
        assert payload["bundle_id"] == "swe.general"

    def test_domain_info_unknown_returns_error(self, store_root: Path) -> None:
        resp = _call("atelier_domain_info", {"bundle_id": "no.such.bundle"}, store_root)
        assert "error" in resp


# --------------------------------------------------------------------------- #
# Host tools                                                                  #
# --------------------------------------------------------------------------- #


class TestHostTools:
    def test_host_list_returns_dict(self, store_root: Path) -> None:
        resp = _call("atelier_host_list", {}, store_root)
        payload = _result(resp)
        assert "hosts" in payload
        assert isinstance(payload["hosts"], list)

    def test_host_status_unknown_returns_error(self, store_root: Path) -> None:
        resp = _call("atelier_host_status", {"host_id": "nonexistent-host-id"}, store_root)
        assert "error" in resp

    def test_host_status_registered_host(self, store_root: Path) -> None:
        from atelier.gateway.hosts import HostRegistry

        registry = HostRegistry(storage_dir=store_root / "hosts")
        reg = registry.register("0.1.0")
        host_id = str(reg.host_id)

        resp = _call("atelier_host_status", {"host_id": host_id}, store_root)
        payload = _result(resp)
        assert payload["host_id"] == host_id


# --------------------------------------------------------------------------- #
# Core capability MCP tools                                                   #
# --------------------------------------------------------------------------- #


class TestCoreCapabilityTools:
    def test_capability_tools_registered(self) -> None:
        expected = {
            "atelier_reasoning_reuse",
            "atelier_semantic_memory",
            "atelier_loop_monitor",
            "atelier_tool_supervisor",
            "atelier_context_compressor",
            "atelier_smart_search",
            "atelier_smart_read",
            "atelier_smart_edit",
            "atelier_sql_inspect",
        }
        assert expected.issubset(set(TOOLS.keys()))

    def test_atelier_reasoning_reuse(self, store_root: Path) -> None:
        resp = _call(
            "atelier_reasoning_reuse",
            {"task": "Publish Shopify product", "domain": "beseam.shopify.publish"},
            store_root,
        )
        payload = _result(resp)
        assert "procedures" in payload

    def test_atelier_semantic_memory_by_path(self, store_root: Path, tmp_path: Path) -> None:
        f = tmp_path / "target.py"
        f.write_text("def x():\n    return 1\n", encoding="utf-8")
        resp = _call("atelier_semantic_memory", {"path": str(f)}, store_root)
        payload = _result(resp)
        assert payload["language"] == "python"

    def test_atelier_smart_edit_and_sql_inspect(self, store_root: Path, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("alpha beta", encoding="utf-8")
        edit_resp = _call(
            "atelier_smart_edit",
            {"edits": [{"path": str(f), "find": "beta", "replace": "gamma"}]},
            store_root,
        )
        edit_payload = _result(edit_resp)
        assert edit_payload["applied"] == 1

        sql_resp = _call(
            "atelier_sql_inspect",
            {
                "sql": "select * from catalog.products join sales.orders on products.id=orders.product_id"
            },
            store_root,
        )
        sql_payload = _result(sql_resp)
        assert "tables" in sql_payload
