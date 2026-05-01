"""MCP-backed SDK client.

This client supports the MCP-standard reasoning tools directly. For richer
read operations like listing ReasonBlocks it falls back to a local store at
``root`` so external hosts can embed Atelier without shelling out.
"""

from __future__ import annotations

from typing import Any

from atelier.core.foundation.models import (
    PlanCheckResult,
    RescueResult,
    RubricResult,
    TraceStatus,
    ValidationResult,
)
from atelier.gateway.adapters import mcp_server
from atelier.gateway.sdk.client import MCPToolTransport, ReasoningContextResult, TraceRecordResult
from atelier.gateway.sdk.local import LocalClient


class _LoopbackTransport(MCPToolTransport):
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tools = {
            "get_reasoning_context": mcp_server.tool_get_reasoning_context,
            "check_plan": mcp_server.tool_check_plan,
            "rescue_failure": mcp_server.tool_rescue_failure,
            "run_rubric_gate": mcp_server.tool_run_rubric_gate,
            "record_trace": mcp_server.tool_record_trace,
        }
        return tools[name](arguments)


class MCPClient(LocalClient):
    def __init__(
        self, *, root: str = ".atelier", transport: MCPToolTransport | None = None
    ) -> None:
        self._transport = transport or _LoopbackTransport()
        super().__init__(root=root)

    def get_reasoning_context(
        self,
        *,
        task: str,
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
        max_blocks: int = 5,
    ) -> ReasoningContextResult:
        payload = self._transport.call_tool(
            "get_reasoning_context",
            {
                "task": task,
                "domain": domain,
                "files": files or [],
                "tools": tools or [],
                "errors": errors or [],
                "max_blocks": max_blocks,
            },
        )
        return ReasoningContextResult.model_validate(payload)

    def check_plan(
        self,
        *,
        task: str,
        plan: list[str],
        domain: str | None = None,
        files: list[str] | None = None,
        tools: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> PlanCheckResult:
        payload = self._transport.call_tool(
            "check_plan",
            {
                "task": task,
                "plan": plan,
                "domain": domain,
                "files": files or [],
                "tools": tools or [],
                "errors": errors or [],
            },
        )
        return PlanCheckResult.model_validate(payload)

    def rescue_failure(
        self,
        *,
        task: str,
        error: str,
        domain: str | None = None,
        files: list[str] | None = None,
        recent_actions: list[str] | None = None,
    ) -> RescueResult:
        payload = self._transport.call_tool(
            "rescue_failure",
            {
                "task": task,
                "error": error,
                "domain": domain,
                "files": files or [],
                "recent_actions": recent_actions or [],
            },
        )
        return RescueResult.model_validate(payload)

    def run_rubric_gate(self, *, rubric_id: str, checks: dict[str, bool | None]) -> RubricResult:
        payload = self._transport.call_tool(
            "run_rubric_gate",
            {"rubric_id": rubric_id, "checks": checks},
        )
        return RubricResult.model_validate(payload)

    def record_trace(
        self,
        *,
        agent: str,
        domain: str,
        task: str,
        status: TraceStatus,
        files_touched: list[str] | None = None,
        commands_run: list[str] | None = None,
        errors_seen: list[str] | None = None,
        diff_summary: str = "",
        output_summary: str = "",
        validation_results: list[ValidationResult] | None = None,
    ) -> TraceRecordResult:
        payload = self._transport.call_tool(
            "record_trace",
            {
                "agent": agent,
                "domain": domain,
                "task": task,
                "status": status,
                "files_touched": files_touched or [],
                "commands_run": commands_run or [],
                "errors_seen": errors_seen or [],
                "diff_summary": diff_summary,
                "output_summary": output_summary,
                "validation_results": [
                    result.model_dump(mode="json") for result in (validation_results or [])
                ],
            },
        )
        payload = {"id": str(payload.get("id") or payload.get("run_id") or "")}
        return TraceRecordResult.model_validate(payload)
