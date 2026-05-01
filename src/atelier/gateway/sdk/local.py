"""Local in-process SDK client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atelier.core.foundation.models import (
    PlanCheckResult,
    ReasonBlock,
    RescueResult,
    Rubric,
    RubricResult,
    Trace,
    TraceStatus,
    ValidationResult,
    to_jsonable,
)
from atelier.core.foundation.plan_checker import check_plan
from atelier.core.foundation.rubric_gate import run_rubric
from atelier.core.improvement.failure_analyzer import analyze_failures
from atelier.gateway.adapters.runtime import ReasoningRuntime
from atelier.gateway.sdk.client import (
    AtelierClient,
    EvalRecord,
    EvalRunResult,
    FailureAnalysisResult,
    ReasoningContextResult,
    SavingsSummary,
    TraceRecordResult,
)
from atelier.infra.runtime.cost_tracker import CostTracker


class LocalClient(AtelierClient):
    def __init__(self, *, root: str = ".atelier") -> None:
        self.root = Path(root)
        self.runtime = ReasoningRuntime(self.root)
        self.store = self.runtime.store
        super().__init__()

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
        return ReasoningContextResult(
            context=self.runtime.get_reasoning_context(
                task=task,
                domain=domain,
                files=files,
                tools=tools,
                errors=errors,
                max_blocks=max_blocks,
            )
        )

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
        return check_plan(
            self.store,
            task=task,
            plan=plan,
            domain=domain,
            files=files or [],
            tools=tools or [],
            errors=errors or [],
        )

    def rescue_failure(
        self,
        *,
        task: str,
        error: str,
        domain: str | None = None,
        files: list[str] | None = None,
        recent_actions: list[str] | None = None,
    ) -> RescueResult:
        return self.runtime.rescue_failure(
            task=task,
            error=error,
            domain=domain,
            files=files,
            recent_actions=recent_actions,
        )

    def run_rubric_gate(self, *, rubric_id: str, checks: dict[str, bool | None]) -> RubricResult:
        rubric = self.store.get_rubric(rubric_id)
        if rubric is None:
            raise KeyError(f"rubric not found: {rubric_id}")
        return run_rubric(rubric, checks)

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
        trace = Trace(
            id=Trace.make_id(task, agent),
            agent=agent,
            domain=domain,
            task=task,
            status=status,
            files_touched=files_touched or [],
            commands_run=commands_run or [],
            errors_seen=errors_seen or [],
            diff_summary=diff_summary,
            output_summary=output_summary,
            validation_results=validation_results or [],
        )
        self.store.record_trace(trace)
        return TraceRecordResult(id=trace.id)

    def analyze_failures(
        self,
        *,
        domain: str | None = None,
        limit: int = 100,
    ) -> FailureAnalysisResult:
        traces = self.store.list_traces(domain=domain, status="failed", limit=limit)
        return FailureAnalysisResult(clusters=analyze_failures([to_jsonable(t) for t in traces]))

    def get_savings(self) -> SavingsSummary:
        return SavingsSummary.model_validate(CostTracker(self.root).total_savings())

    def _list_reasonblocks(
        self,
        *,
        domain: str | None = None,
        include_deprecated: bool = False,
    ) -> list[ReasonBlock]:
        return self.store.list_blocks(domain=domain, include_deprecated=include_deprecated)

    def _search_reasonblocks(self, *, query: str, limit: int = 20) -> list[ReasonBlock]:
        return self.store.search_blocks(query, limit=limit)

    def _get_reasonblock(self, block_id: str) -> ReasonBlock | None:
        return self.store.get_block(block_id)

    def _list_rubrics(self, *, domain: str | None = None) -> list[Rubric]:
        return self.store.list_rubrics(domain=domain)

    def _get_rubric(self, rubric_id: str) -> Rubric | None:
        return self.store.get_rubric(rubric_id)

    def _get_trace(self, trace_id: str) -> Trace | None:
        return self.store.get_trace(trace_id)

    def _list_traces(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Trace]:
        return self.store.list_traces(domain=domain, status=status, limit=limit)

    def _list_evals(self, *, domain: str | None = None) -> list[dict[str, Any]]:
        evals_dir = self.root / "evals"
        if not evals_dir.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(evals_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if domain and payload.get("domain") != domain:
                continue
            items.append(payload)
        return items

    def _run_evals(
        self,
        *,
        case_id: str | None = None,
        domain: str | None = None,
        limit: int = 50,
    ) -> EvalRunResult:
        items = self._list_evals(domain=domain)
        if case_id is not None:
            items = [item for item in items if item.get("id") == case_id]
        items = items[:limit]
        results: list[EvalRecord] = []
        for item in items:
            plan = [str(step) for step in item.get("plan", [])]
            task = str(item.get("task", item.get("description", "Untitled eval")))
            actual = self.check_plan(
                task=task,
                plan=plan,
                domain=item.get("domain"),
            ).status
            results.append(
                EvalRecord(
                    case_id=str(item.get("id", "unknown")),
                    domain=str(item.get("domain", "unknown")),
                    description=str(item.get("description", "")),
                    expected_status=str(item.get("expected_status", "pass")),
                    actual_status=actual,
                    passed=actual == str(item.get("expected_status", "pass")),
                )
            )
        return EvalRunResult(results=results)
