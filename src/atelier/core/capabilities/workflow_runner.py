from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from atelier.core.capabilities.workflow_context import StepResult, WorkflowContextState
from atelier.core.capabilities.workflow_schema import (
    WorkflowDefinition,
    WorkflowStepDefinition,
    step_dependencies,
    step_is_safe_parallel,
    validate_workflow_definition,
)
from atelier.infra.runtime.run_ledger import RunLedger

AgentExecutor = Callable[[WorkflowStepDefinition, str, WorkflowContextState], Any]
ToolExecutor = Callable[[WorkflowStepDefinition, dict[str, Any], WorkflowContextState], Any]
ShellExecutor = Callable[[WorkflowStepDefinition, str, dict[str, Any]], Any]


@dataclass(frozen=True)
class WorkflowRunResult:
    run_id: str
    status: str
    step_order: list[str]
    step_results: dict[str, StepResult]
    failed_step_id: str | None = None


def build_execution_waves(definition: WorkflowDefinition) -> list[tuple[str, ...]]:
    validated = validate_workflow_definition(definition)
    order = [step.step_id for step in validated.steps]
    by_id = {step.step_id: step for step in validated.steps}
    deps = {step_id: set(values) for step_id, values in step_dependencies(validated).items()}
    completed: set[str] = set()
    waves: list[tuple[str, ...]] = []

    while len(completed) < len(order):
        ready = [step_id for step_id in order if step_id not in completed and deps[step_id].issubset(completed)]
        if not ready:
            raise ValueError("workflow contains unresolved dependencies")
        first = by_id[ready[0]]
        if step_is_safe_parallel(first):
            wave = tuple(step_id for step_id in ready if step_is_safe_parallel(by_id[step_id]))
        else:
            wave = (ready[0],)
        completed.update(wave)
        waves.append(wave)
    return waves


class WorkflowRunner:
    def __init__(
        self,
        *,
        agent_executor: AgentExecutor,
        tool_executor: ToolExecutor,
        shell_executor: ShellExecutor,
    ) -> None:
        self._agent_executor = agent_executor
        self._tool_executor = tool_executor
        self._shell_executor = shell_executor

    def _definition_hash(self, definition: WorkflowDefinition) -> str:
        payload = {
            "workflow_id": definition.workflow_id,
            "steps": [
                {
                    "step_id": step.step_id,
                    "kind": step.kind,
                    "next_steps": list(step.next_steps),
                    "fork_from": step.fork_from,
                    "prompt": step.prompt,
                    "tool": step.tool,
                    "args": step.args,
                    "command": step.command,
                    "output_name": step.output_name,
                    "json_output": step.json_output,
                    "interactive": step.interactive,
                }
                for step in definition.steps
            ],
        }
        return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _normalize_executor_result(
        self, step: WorkflowStepDefinition, raw: Any, *, duration_seconds: float
    ) -> StepResult:
        if isinstance(raw, StepResult):
            return StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status=raw.status,
                output=raw.output,
                output_json=raw.output_json,
                duration_seconds=raw.duration_seconds or duration_seconds,
                cost_usd=raw.cost_usd,
                error=raw.error,
            )
        if isinstance(raw, dict):
            raw_output_json = raw.get("output_json")
            output_json: dict[str, Any] = dict(raw_output_json) if isinstance(raw_output_json, dict) else dict(raw)
            if "output" in raw:
                output = raw.get("output")
            elif isinstance(raw.get("content"), str):
                output = raw.get("content")
            else:
                output = json.dumps(raw, sort_keys=True)
            return StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status=str(raw.get("status") or "done"),
                output=output,
                output_json=output_json,
                duration_seconds=float(raw.get("duration_seconds") or duration_seconds),
                cost_usd=float(raw.get("cost_usd") or 0.0),
                error=str(raw.get("error") or ""),
            )
        return StepResult(
            step_id=step.step_id,
            kind=step.kind,
            status="done",
            output=raw,
            output_json={},
            duration_seconds=duration_seconds,
        )

    def _run_step(
        self,
        step: WorkflowStepDefinition,
        context_state: WorkflowContextState,
        ledger: RunLedger | None,
    ) -> StepResult:
        start = time.perf_counter()
        if ledger is not None:
            ledger.record_workflow_step_event(step_id=step.step_id, event="start", kind=step.kind, status="running")
        try:
            if step.kind == "agent":
                rendered_prompt = context_state.render_value(step.prompt)
                raw_result = self._agent_executor(step, str(rendered_prompt), context_state)
            elif step.kind == "tool":
                rendered_args = context_state.render_value(step.args)
                raw_result = self._tool_executor(step, dict(rendered_args), context_state)
            elif step.kind == "shell":
                rendered_command = context_state.render_value(step.command)
                forked = context_state.fork_step_context(step.fork_from) if step.fork_from else {}
                raw_result = self._shell_executor(step, str(rendered_command), forked)
            else:
                raise ValueError(f"unsupported step kind: {step.kind}")
            result = self._normalize_executor_result(step, raw_result, duration_seconds=time.perf_counter() - start)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            result = StepResult(
                step_id=step.step_id,
                kind=step.kind,
                status="failed",
                output="",
                output_json={},
                duration_seconds=time.perf_counter() - start,
                error=str(exc),
            )
        if ledger is not None:
            event = "done" if result.status == "done" else "fail"
            ledger.record_workflow_step_event(step_id=step.step_id, event=event, kind=step.kind, status=result.status)
        return result

    def run(
        self,
        definition: WorkflowDefinition,
        *,
        context_state: WorkflowContextState | None = None,
        ledger: RunLedger | None = None,
    ) -> WorkflowRunResult:
        validated = validate_workflow_definition(definition)
        state = context_state if context_state is not None else WorkflowContextState()
        if not state.run_id:
            state.run_id = uuid.uuid4().hex
        state.status = "running"
        state.definition_hash = self._definition_hash(validated)
        waves = build_execution_waves(validated)
        by_id = {step.step_id: step for step in validated.steps}
        total_steps = len(validated.steps)
        completed_steps = 0

        if ledger is not None:
            ledger.record_workflow_event("workflow_state", {"workflow_step": "execution", "session_phase": "execute"})

        for wave in waves:
            results: list[StepResult] = []
            if len(wave) > 1:
                with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                    futures = [pool.submit(self._run_step, by_id[step_id], state, ledger) for step_id in wave]
                    for future in futures:
                        results.append(future.result())
            else:
                results.append(self._run_step(by_id[wave[0]], state, ledger))

            results_by_id = {result.step_id: result for result in results}
            ordered_results = [results_by_id[step_id] for step_id in wave]
            for result in ordered_results:
                state.record_step_result(result)
                if result.status == "done":
                    completed_steps += 1
                if ledger is not None:
                    ledger.record_workflow_event(
                        "task_progress",
                        {
                            "task_id": result.step_id,
                            "workflow_step": "execution",
                            "completed_tasks": completed_steps,
                            "remaining_tasks": total_steps - completed_steps,
                        },
                    )
                if result.status != "done":
                    state.status = "failed"
                    return WorkflowRunResult(
                        run_id=state.run_id,
                        status="failed",
                        step_order=list(state.step_order),
                        step_results=dict(state.step_results),
                        failed_step_id=result.step_id,
                    )

        state.status = "success"
        return WorkflowRunResult(
            run_id=state.run_id,
            status="success",
            step_order=list(state.step_order),
            step_results=dict(state.step_results),
        )


__all__ = ["WorkflowRunResult", "WorkflowRunner", "build_execution_waves"]
