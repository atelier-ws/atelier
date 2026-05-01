"""Remote HTTP SDK client."""

from __future__ import annotations

import urllib.parse
from typing import Any, Protocol, cast

from atelier.core.foundation.models import (
    FailureCluster,
    PlanCheckResult,
    ReasonBlock,
    RescueResult,
    Rubric,
    RubricResult,
    Trace,
    TraceStatus,
    ValidationResult,
)
from atelier.gateway.adapters import remote_client as service_remote_client
from atelier.gateway.sdk.client import (
    AtelierClient,
    EvalRunResult,
    FailureAnalysisResult,
    ReasoningContextResult,
    SavingsSummary,
    TraceRecordResult,
)


class _ServiceClient(Protocol):
    def get_reasoning_context(self, args: dict[str, Any]) -> dict[str, Any]: ...
    def check_plan(self, args: dict[str, Any]) -> dict[str, Any]: ...
    def rescue_failure(self, args: dict[str, Any]) -> dict[str, Any]: ...
    def run_rubric_gate(self, args: dict[str, Any]) -> dict[str, Any]: ...
    def record_trace(self, args: dict[str, Any]) -> dict[str, Any]: ...
    def list_reasonblocks(
        self,
        *,
        domain: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_reasonblock(self, block_id: str) -> dict[str, Any]: ...
    def list_rubrics(self, *, domain: str | None = None) -> list[dict[str, Any]]: ...
    def get_rubric(self, rubric_id: str) -> dict[str, Any]: ...
    def analyze_failures(
        self, *, domain: str | None = None, limit: int = 100
    ) -> dict[str, Any]: ...
    def get_savings(self) -> dict[str, Any]: ...
    def _get(self, path: str) -> dict[str, Any]: ...
    def list_evals(self, *, domain: str | None = None) -> dict[str, Any]: ...
    def run_evals(self, *, domain: str | None = None, limit: int = 50) -> dict[str, Any]: ...


class RemoteClient(AtelierClient):
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = cast(
            _ServiceClient,
            service_remote_client.RemoteClient(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
            ),
        )
        super().__init__()

    def _ensure_ok(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("ok") is False:
            detail = payload.get("detail") or payload.get("error") or "remote request failed"
            raise RuntimeError(str(detail))
        return payload

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
        payload = self._ensure_ok(
            self._client.get_reasoning_context(
                {
                    "task": task,
                    "domain": domain,
                    "files": files or [],
                    "tools": tools or [],
                    "errors": errors or [],
                    "max_blocks": max_blocks,
                }
            )
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
        payload = self._ensure_ok(
            self._client.check_plan(
                {
                    "task": task,
                    "plan": plan,
                    "domain": domain,
                    "files": files or [],
                    "tools": tools or [],
                    "errors": errors or [],
                }
            )
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
        payload = self._ensure_ok(
            self._client.rescue_failure(
                {
                    "task": task,
                    "error": error,
                    "domain": domain,
                    "files": files or [],
                    "recent_actions": recent_actions or [],
                }
            )
        )
        return RescueResult.model_validate(payload)

    def run_rubric_gate(self, *, rubric_id: str, checks: dict[str, bool | None]) -> RubricResult:
        payload = self._ensure_ok(
            self._client.run_rubric_gate({"rubric_id": rubric_id, "checks": checks})
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
        payload = self._ensure_ok(
            self._client.record_trace(
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
                }
            )
        )
        return TraceRecordResult.model_validate(payload)

    def analyze_failures(
        self,
        *,
        domain: str | None = None,
        limit: int = 100,
    ) -> FailureAnalysisResult:
        payload = self._ensure_ok(self._client.analyze_failures(domain=domain, limit=limit))
        return FailureAnalysisResult(
            clusters=[FailureCluster.model_validate(item) for item in payload.get("clusters", [])]
        )

    def get_savings(self) -> SavingsSummary:
        payload = self._ensure_ok(self._client.get_savings())
        return SavingsSummary.model_validate(payload)

    def _list_reasonblocks(
        self,
        *,
        domain: str | None = None,
        include_deprecated: bool = False,
    ) -> list[ReasonBlock]:
        items = self._client.list_reasonblocks(domain=domain)
        blocks = [ReasonBlock.model_validate(item) for item in items]
        if include_deprecated:
            return blocks
        return [block for block in blocks if block.status == "active"]

    def _search_reasonblocks(self, *, query: str, limit: int = 20) -> list[ReasonBlock]:
        items = self._client.list_reasonblocks(query=query)
        return [ReasonBlock.model_validate(item) for item in items[:limit]]

    def _get_reasonblock(self, block_id: str) -> ReasonBlock | None:
        payload = self._client.get_reasonblock(block_id)
        return ReasonBlock.model_validate(payload) if payload else None

    def _list_rubrics(self, *, domain: str | None = None) -> list[Rubric]:
        return [Rubric.model_validate(item) for item in self._client.list_rubrics(domain=domain)]

    def _get_rubric(self, rubric_id: str) -> Rubric | None:
        payload = self._client.get_rubric(rubric_id)
        return Rubric.model_validate(payload) if payload else None

    def _get_trace(self, trace_id: str) -> Trace | None:
        payload = self._client._get(f"/traces/{urllib.parse.quote(trace_id)}")
        if isinstance(payload, dict) and payload.get("id"):
            return Trace.model_validate(payload)
        return None

    def _list_traces(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Trace]:
        params: list[str] = []
        if domain:
            params.append(f"domain={urllib.parse.quote(domain)}")
        if status:
            params.append(f"status={urllib.parse.quote(status)}")
        params.append(f"limit={limit}")
        suffix = f"?{'&'.join(params)}" if params else ""
        payload = self._client._get(f"/traces{suffix}")
        return [Trace.model_validate(item) for item in payload] if isinstance(payload, list) else []

    def _list_evals(self, *, domain: str | None = None) -> list[dict[str, Any]]:
        payload = self._ensure_ok(self._client.list_evals(domain=domain))
        return [item for item in payload.get("evals", []) if isinstance(item, dict)]

    def _run_evals(
        self,
        *,
        case_id: str | None = None,
        domain: str | None = None,
        limit: int = 50,
    ) -> EvalRunResult:
        payload = self._ensure_ok(self._client.run_evals(domain=domain, limit=limit))
        if case_id is not None:
            payload["case_id"] = case_id
        return EvalRunResult.model_validate(payload)
