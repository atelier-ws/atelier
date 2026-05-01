"""Tests for domain bundle MCP tools and CLI integration (replaces Phase D.3/D.4 pack tests)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestMCPDomainTools:
    """Test MCP domain tool registration and schemas."""

    def test_mcp_server_has_domain_tools(self) -> None:
        from atelier.gateway.adapters import mcp_server

        assert "atelier_domain_list" in mcp_server.TOOLS
        assert "atelier_domain_info" in mcp_server.TOOLS

    def test_mcp_server_no_pack_tools(self) -> None:
        from atelier.gateway.adapters import mcp_server

        assert "atelier_pack_list" not in mcp_server.TOOLS
        assert "atelier_pack_install" not in mcp_server.TOOLS
        assert "atelier_pack_info" not in mcp_server.TOOLS
        assert "atelier_pack_validate" not in mcp_server.TOOLS

    def test_mcp_host_tools_still_present(self) -> None:
        from atelier.gateway.adapters import mcp_server

        assert "atelier_host_list" in mcp_server.TOOLS
        assert "atelier_host_status" in mcp_server.TOOLS

    def test_mcp_domain_list_schema(self) -> None:
        from atelier.gateway.adapters import mcp_server

        tool = mcp_server.TOOLS["atelier_domain_list"]
        assert callable(tool["handler"])
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"

    def test_mcp_domain_info_schema(self) -> None:
        from atelier.gateway.adapters import mcp_server

        tool = mcp_server.TOOLS["atelier_domain_info"]
        assert callable(tool["handler"])
        schema = tool["inputSchema"]
        assert "bundle_id" in schema["required"]
        assert "bundle_id" in schema["properties"]

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


class TestMCPDomainToolHandlers:
    """Functional tests for domain MCP tool handlers."""

    def test_mcp_domain_list_handler_returns_bundles(self) -> None:
        from atelier.gateway.adapters.mcp_server import tool_atelier_domain_list

        result = tool_atelier_domain_list({})
        assert isinstance(result, dict)
        assert "bundles" in result
        assert isinstance(result["bundles"], list)

    def test_mcp_domain_list_contains_swe_general(self) -> None:
        from atelier.gateway.adapters.mcp_server import tool_atelier_domain_list

        result = tool_atelier_domain_list({})
        ids = {item["bundle_id"] for item in result["bundles"]}
        assert "swe.general" in ids

    def test_mcp_domain_info_handler_returns_bundle_info(self) -> None:
        from atelier.gateway.adapters.mcp_server import tool_atelier_domain_info

        result = tool_atelier_domain_info({"bundle_id": "swe.general"})
        assert isinstance(result, dict)
        assert result["bundle_id"] == "swe.general"

    def test_mcp_domain_info_raises_for_unknown(self) -> None:
        from atelier.gateway.adapters.mcp_server import tool_atelier_domain_info

        with pytest.raises(ValueError, match="not found"):
            tool_atelier_domain_info({"bundle_id": "does.not.exist"})

    def test_mcp_host_list_handler_signature(self) -> None:
        from atelier.gateway.adapters.mcp_server import tool_atelier_host_list

        result = tool_atelier_host_list({})
        assert isinstance(result, dict)
        assert "hosts" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
