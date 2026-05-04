"""Regression tests for the reduced MCP tool surface."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestMCPTools:
    """Test MCP tool registration and schemas."""

    def test_removed_tools_absent(self) -> None:
        from atelier.gateway.adapters import mcp_server

        removed = {
            "atelier_domain_list",
            "atelier_domain_info",
            "atelier_host_list",
            "atelier_host_status",
            "atelier_smart_search",
            "atelier_search",
            "atelier_smart_edit",
            "atelier_symbol_search",
            "atelier_extract_reasonblock",
            "atelier_record_call",
            "atelier_record_note",
            "atelier_get_run_ledger",
            "atelier_update_run_ledger",
            "atelier_monitor_event",
            "atelier_get_environment",
            "atelier_cached_grep",
            "atelier_status",
            "atelier_reasoning_reuse",
            "atelier_semantic_memory",
            "atelier_loop_monitor",
            "atelier_tool_supervisor",
            "atelier_context_compressor",
            "atelier_bash_intercept",
            "atelier_module_summary",
        }
        for name in removed:
            assert name not in mcp_server.TOOLS

    def test_core_tools_present(self) -> None:
        from atelier.gateway.adapters import mcp_server

        expected = {
            "atelier_get_reasoning_context",
            "atelier_check_plan",
            "atelier_rescue_failure",
            "atelier_record_trace",
            "atelier_run_rubric_gate",
            "atelier_compress_context",
            "atelier_sql_inspect",
            "atelier_memory_upsert_block",
            "atelier_memory_get_block",
            "atelier_memory_archive",
            "atelier_memory_recall",
            "atelier_smart_read",
        }
        assert expected.issubset(set(mcp_server.TOOLS.keys()))

    def test_mcp_server_no_pack_tools(self) -> None:
        from atelier.gateway.adapters import mcp_server

        assert "atelier_pack_list" not in mcp_server.TOOLS
        assert "atelier_pack_install" not in mcp_server.TOOLS
        assert "atelier_pack_info" not in mcp_server.TOOLS
        assert "atelier_pack_validate" not in mcp_server.TOOLS

    def test_all_tools_have_handlers(self) -> None:
        from atelier.gateway.adapters import mcp_server

        for tool_name, tool_spec in mcp_server.TOOLS.items():
            if tool_name.startswith("atelier_"):
                assert "handler" in tool_spec, f"{tool_name} missing handler"
                assert callable(tool_spec["handler"]), f"{tool_name} handler not callable"
                assert "description" in tool_spec, f"{tool_name} missing description"
                assert "inputSchema" in tool_spec, f"{tool_name} missing inputSchema"

    def test_all_schemas_valid_json_schema(self) -> None:
        from atelier.gateway.adapters import mcp_server

        for tool_name, tool_spec in mcp_server.TOOLS.items():
            if tool_name.startswith("atelier_"):
                schema = tool_spec["inputSchema"]
                assert isinstance(schema, dict)
                assert schema.get("type") in ("object", None)
                if "properties" in schema:
                    assert isinstance(schema["properties"], dict)
                if "required" in schema:
                    assert isinstance(schema["required"], list)


class TestMCPToolHandlers:
    """Functional tests for Core-6 MCP handlers."""

    def test_core_six_all_have_handlers(self) -> None:
        from atelier.gateway.adapters.mcp_server import TOOLS

        for tool_name in TOOLS:
            assert callable(TOOLS[tool_name]["handler"])
            assert TOOLS[tool_name]["description"]
            assert "inputSchema" in TOOLS[tool_name]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
