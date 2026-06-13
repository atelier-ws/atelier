from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from atelier.core.capabilities.cross_vendor_routing.configuration import RouteConfigError
from atelier.core.capabilities.cross_vendor_routing.router import NoFeasibleRouteError
from atelier.core.capabilities.default_definitions import (
    DefaultRegistry,
    DefaultWorkflow,
    DefaultWorkflowStep,
    build_default_registry,
)
from atelier.core.capabilities.host_runners import resolve_swarm_runner_command
from atelier.core.capabilities.model_settings import (
    normalize_model_for_host,
    resolve_host_model,
    resolve_runtime_model,
)
from atelier.core.capabilities.owned_execution_cache_affinity import (
    cache_affinity_hint,
    latest_cache_affinity,
)
from atelier.core.capabilities.owned_execution_lanes import (
    OwnedExecutionError,
    execute_owned_prompt,
)
from atelier.core.capabilities.owned_execution_routing import (
    OwnedCachePolicy,
    OwnedRouteDecision,
    OwnedRouteRequest,
    select_owned_route,
)
from atelier.core.capabilities.tool_supervision.workspace_hygiene import (
    scratch_leftovers,
    snapshot_workspace,
)
from atelier.core.capabilities.workflow_context import StepResult, WorkflowContextState
from atelier.core.capabilities.workflow_runner import WorkflowRunner
from atelier.core.capabilities.workflow_schema import WorkflowDefinition, WorkflowStepDefinition
from atelier.core.capabilities.workflow_spawn import (
    build_spawn_envelope,
    compile_child_prompt,
    compile_prompt_text,
    format_transcript,
)
from atelier.core.foundation.paths import default_store_root


@dataclass(frozen=True)
class HarnessFeedback:
    summary: str
    failing_checks: tuple[str, ...] = ()
    raw_log_excerpt: str = ""
    artifact_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "failing_checks": list(self.failing_checks),
            "raw_log_excerpt": self.raw_log_excerpt,
            "artifact_paths": list(self.artifact_paths),
        }


@dataclass(frozen=True)
class SolverStepArtifact:
    step_id: str
    role_id: str
    phase_prompt_id: str
    effort: str
    read_mode_hint: str
    status: str
    input_prompt: str
    output: str
    output_json: dict[str, Any]
    execution_receipt: dict[str, Any]
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    changed_files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "role_id": self.role_id,
            "phase_prompt_id": self.phase_prompt_id,
            "effort": self.effort,
            "read_mode_hint": self.read_mode_hint,
            "status": self.status,
            "input_prompt": self.input_prompt,
            "output": self.output,
            "output_json": dict(self.output_json),
            "execution_receipt": dict(self.execution_receipt),
            "duration_seconds": self.duration_seconds,
            "cost_usd": self.cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "changed_files": list(self.changed_files),
        }


@dataclass(frozen=True)
class BenchmarkAttempt:
    attempt_number: int
    workflow_id: str
    profile_id: str
    task_prompt: str
    status: str
    step_artifacts: tuple[SolverStepArtifact, ...] = ()
    retry_context: str = ""
    forked_from_attempt: int | None = None
    review_raw_output: str = ""
    review_verdict_json: dict[str, Any] | None = None
    harness_feedback: HarnessFeedback | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "workflow_id": self.workflow_id,
            "profile_id": self.profile_id,
            "task_prompt": self.task_prompt,
            "status": self.status,
            "step_artifacts": [artifact.to_dict() for artifact in self.step_artifacts],
            "retry_context": self.retry_context,
            "forked_from_attempt": self.forked_from_attempt,
            "review_raw_output": self.review_raw_output,
            "review_verdict_json": dict(self.review_verdict_json or {}),
            "harness_feedback": self.harness_feedback.to_dict() if self.harness_feedback is not None else None,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class SolverEvent:
    event: str
    run_id: str
    attempt_number: int
    step_id: str = ""
    status: str = ""
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "event": self.event,
            "run_id": self.run_id,
            "attempt_number": self.attempt_number,
        }
        if self.step_id:
            data["step_id"] = self.step_id
        if self.status:
            data["status"] = self.status
        if self.payload:
            data["payload"] = dict(self.payload)
        return data


@dataclass(frozen=True)
class SolverRunArtifact:
    run_id: str
    task_prompt: str
    profile_id: str
    workflow_id: str
    status: str
    attempts: tuple[BenchmarkAttempt, ...]
    events: tuple[SolverEvent, ...]
    provider: str = ""
    runner: str = ""
    transport: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_prompt": self.task_prompt,
            "profile_id": self.profile_id,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "events": [event.to_dict() for event in self.events],
            "provider": self.provider,
            "runner": self.runner,
            "transport": self.transport,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class WrittenSolverArtifacts:
    run_json_path: Path
    stream_jsonl_path: Path


def build_retry_context(
    previous_attempt: BenchmarkAttempt,
    feedback: HarnessFeedback | None,
    *,
    repo_root: Path | None = None,
    registry: DefaultRegistry | None = None,
) -> str:
    defaults = registry or build_default_registry(repo_root)
    profile = defaults.benchmark_profiles[previous_attempt.profile_id]
    lines = [
        "Retry the same benchmark task using the prior attempt context.",
        "",
        "Original task:",
        previous_attempt.task_prompt,
        "",
        "Prior review verdict:",
        json.dumps(previous_attempt.review_verdict_json or {"verdict": "NEEDS_FIX"}, sort_keys=True),
    ]
    if feedback is not None:
        lines.extend(
            [
                "",
                "Harness feedback:",
                feedback.summary,
            ]
        )
        if feedback.failing_checks:
            lines.extend(["Failed checks:"] + [f"- {check}" for check in feedback.failing_checks])
        if feedback.raw_log_excerpt:
            lines.extend(["", "Relevant log excerpt:", feedback.raw_log_excerpt])
        if feedback.artifact_paths:
            lines.extend(["", "Related artifacts:"] + [f"- {path}" for path in feedback.artifact_paths])
    lines.extend(["", "Command discipline:"] + [f"- {rule}" for rule in profile.command_rules])
    return "\n".join(lines).strip()


def run_benchmark_solver(
    task_prompt: str,
    *,
    repo_root: Path | None = None,
    profile_id: str = "terminalbench-owned-solver",
    step_executor: Any | None = None,
    feedback_provider: Any | None = None,
    max_attempts: int | None = None,
    route_mode: str = "auto",
    provider: str | None = None,
    model: str | None = None,
    runner: str | None = None,
) -> SolverRunArtifact:
    defaults = build_default_registry(repo_root)
    profile = defaults.benchmark_profiles[profile_id]
    workflow = defaults.workflows[profile.workflow_id]
    run_id = uuid.uuid4().hex
    limit = max_attempts if max_attempts is not None else profile.retry_limit
    try:
        route_decision, resolved_provider, resolved_runner, resolved_model, resolved_transport = (
            _resolve_solver_execution_route(
                task_prompt=task_prompt,
                defaults=defaults,
                profile_id=profile_id,
                route_mode=route_mode,
                provider=provider,
                model=model,
                runner=runner,
                workspace_root=Path.cwd().resolve() if repo_root is None else repo_root,
            )
        )
    except (RouteConfigError, NoFeasibleRouteError):
        if step_executor is None or route_mode != "auto" or provider or model or runner:
            raise
        fallback_model = resolve_runtime_model(
            profile.role_id, Path.cwd().resolve() if repo_root is None else repo_root
        )
        fallback_runner = "claude"
        route_decision = None
        resolved_provider = _provider_for_model(fallback_model)
        resolved_runner = fallback_runner
        resolved_model = fallback_model
        resolved_transport = ""
    executor = step_executor or _default_step_executor(
        repo_root=Path.cwd().resolve() if repo_root is None else repo_root,
        route_decision=route_decision,
        runner=resolved_runner,
        model=resolved_model,
    )
    events: list[SolverEvent] = [SolverEvent(event="start", run_id=run_id, attempt_number=1)]
    attempts: list[BenchmarkAttempt] = []
    retry_context = ""
    previous_attempt: BenchmarkAttempt | None = None
    final_status = "failed"
    workspace_root = Path.cwd().resolve() if repo_root is None else repo_root
    hygiene_baseline = snapshot_workspace(workspace_root)

    for attempt_number in range(1, limit + 1):
        events.append(SolverEvent(event="attempt", run_id=run_id, attempt_number=attempt_number, status="running"))
        attempt = _run_attempt(
            run_id=run_id,
            attempt_number=attempt_number,
            task_prompt=task_prompt,
            retry_context=retry_context,
            previous_attempt=previous_attempt,
            workflow=workflow,
            profile_id=profile_id,
            defaults=defaults,
            step_executor=executor,
        )
        feedback = feedback_provider(attempt) if feedback_provider is not None else None
        if feedback is not None:
            attempt = replace(attempt, harness_feedback=feedback)
        attempts.append(attempt)
        events.extend(
            SolverEvent(
                event="step",
                run_id=run_id,
                attempt_number=attempt_number,
                step_id=artifact.step_id,
                status=artifact.status,
            )
            for artifact in attempt.step_artifacts
        )

        verdict = str((attempt.review_verdict_json or {}).get("verdict") or "NEEDS_FIX").upper()
        needs_retry = attempt.status != "success" or verdict != "PASS" or feedback is not None
        if not needs_retry:
            final_status = "success"
            break
        if attempt_number >= limit:
            final_status = "failed"
            break
        retry_context = build_retry_context(attempt, feedback, repo_root=repo_root, registry=defaults)
        leftovers = scratch_leftovers(workspace_root, hygiene_baseline)
        if leftovers:
            events.append(
                SolverEvent(
                    event="hygiene",
                    run_id=run_id,
                    attempt_number=attempt_number,
                    status="leftovers",
                    payload={"leftovers": leftovers},
                )
            )
            retry_context += (
                "\n\nWorkspace hygiene: these scratch/build files appeared during solving and may fail "
                "file-hygiene checks; remove any the task did not ask for: " + ", ".join(leftovers)
            )
        events.append(
            SolverEvent(
                event="retry",
                run_id=run_id,
                attempt_number=attempt_number + 1,
                status="scheduled",
                payload={"from_attempt": attempt_number},
            )
        )
        previous_attempt = attempt

    final_leftovers = scratch_leftovers(workspace_root, hygiene_baseline)
    if final_leftovers:
        events.append(
            SolverEvent(
                event="hygiene",
                run_id=run_id,
                attempt_number=len(attempts),
                status="leftovers",
                payload={"leftovers": final_leftovers},
            )
        )
    events.append(
        SolverEvent(
            event="complete",
            run_id=run_id,
            attempt_number=len(attempts),
            status=final_status,
        )
    )

    return SolverRunArtifact(
        run_id=run_id,
        task_prompt=task_prompt,
        profile_id=profile_id,
        workflow_id=profile.workflow_id,
        status=final_status,
        attempts=tuple(attempts),
        events=tuple(events),
        provider=resolved_provider,
        runner=resolved_runner,
        transport=resolved_transport,
        model=resolved_model,
        input_tokens=sum(attempt.input_tokens for attempt in attempts),
        output_tokens=sum(attempt.output_tokens for attempt in attempts),
        cache_creation_input_tokens=sum(attempt.cache_creation_input_tokens for attempt in attempts),
        cache_read_input_tokens=sum(attempt.cache_read_input_tokens for attempt in attempts),
        cost_usd=sum(attempt.cost_usd for attempt in attempts),
        duration_seconds=sum(attempt.duration_seconds for attempt in attempts),
    )


def write_solver_artifacts(run: SolverRunArtifact, out_dir: Path) -> WrittenSolverArtifacts:
    out_dir.mkdir(parents=True, exist_ok=True)
    run_json_path = out_dir / "solver-run.json"
    stream_jsonl_path = out_dir / "solver-stream.jsonl"
    run_json_path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
    stream_jsonl_path.write_text(
        "\n".join(json.dumps(event.to_dict()) for event in run.events) + "\n",
        encoding="utf-8",
    )
    return WrittenSolverArtifacts(run_json_path=run_json_path, stream_jsonl_path=stream_jsonl_path)


def _run_attempt(
    *,
    run_id: str,
    attempt_number: int,
    task_prompt: str,
    retry_context: str,
    previous_attempt: BenchmarkAttempt | None,
    workflow: DefaultWorkflow,
    profile_id: str,
    defaults: DefaultRegistry,
    step_executor: Any,
) -> BenchmarkAttempt:
    definition, default_steps = _build_workflow_definition(
        workflow,
        defaults=defaults,
        profile_id=profile_id,
        task_prompt=task_prompt,
        retry_context=retry_context,
    )
    stem_prompt = defaults.render_named_prompt(workflow.stem_prompt_id)
    prior_attempt_history = _step_history_from_attempt(previous_attempt)
    step_histories: dict[str, tuple[dict[str, str], ...]] = {}
    executed_prompts: dict[str, str] = {}

    def agent_executor(
        step: WorkflowStepDefinition,
        rendered_prompt: str,
        context_state: WorkflowContextState,
    ) -> Any:
        default_step = default_steps[step.step_id]
        parent_history = _parent_step_history(
            default_step=default_step,
            step_histories=step_histories,
            prior_attempt_history=prior_attempt_history,
        )
        composed_prompt = _compose_agent_prompt(
            stem_prompt=stem_prompt,
            current_prompt=rendered_prompt,
            transcript=parent_history,
        )
        raw_result = step_executor(default_step, composed_prompt, context_state, attempt_number)
        executed_prompts[step.step_id] = composed_prompt
        step_histories[step.step_id] = (
            *parent_history,
            {
                "step_id": default_step.step_id,
                "phase_prompt_id": default_step.phase_prompt_id,
                "input_prompt": composed_prompt,
                "output": _raw_output_text(raw_result),
            },
        )
        return raw_result

    runner = WorkflowRunner(
        agent_executor=agent_executor,
        tool_executor=lambda *_args, **_kwargs: {
            "status": "failed",
            "error": "tool steps unsupported",
        },
        shell_executor=lambda *_args, **_kwargs: {
            "status": "failed",
            "error": "shell steps unsupported",
        },
    )
    result = runner.run(definition)
    step_artifacts = tuple(
        _step_artifact(default_steps[step_id], result.step_results[step_id], executed_prompts.get(step_id, ""))
        for step_id in result.step_order
        if step_id in result.step_results
    )
    review_result = result.step_results.get("review")
    review_raw_output = str(review_result.output) if review_result is not None else ""
    review_verdict_json = _parse_review_verdict(review_result)
    status = "success" if result.status == "success" and review_verdict_json.get("verdict") == "PASS" else "failed"
    return BenchmarkAttempt(
        attempt_number=attempt_number,
        workflow_id=workflow.workflow_id,
        profile_id=profile_id,
        task_prompt=task_prompt,
        status=status,
        step_artifacts=step_artifacts,
        retry_context=retry_context,
        forked_from_attempt=previous_attempt.attempt_number if previous_attempt is not None else None,
        review_raw_output=review_raw_output,
        review_verdict_json=review_verdict_json,
        input_tokens=sum(item.input_tokens for item in step_artifacts),
        output_tokens=sum(item.output_tokens for item in step_artifacts),
        cache_creation_input_tokens=sum(item.cache_creation_input_tokens for item in step_artifacts),
        cache_read_input_tokens=sum(item.cache_read_input_tokens for item in step_artifacts),
        duration_seconds=sum(item.duration_seconds for item in step_artifacts),
        cost_usd=sum(item.cost_usd for item in step_artifacts),
    )


def _build_workflow_definition(
    workflow: DefaultWorkflow,
    *,
    defaults: DefaultRegistry,
    profile_id: str,
    task_prompt: str,
    retry_context: str,
) -> tuple[WorkflowDefinition, dict[str, DefaultWorkflowStep]]:
    steps: list[WorkflowStepDefinition] = []
    by_id: dict[str, DefaultWorkflowStep] = {}
    profile = defaults.benchmark_profiles[profile_id]
    for default_step in workflow.steps:
        by_id[default_step.step_id] = default_step
        prompt_parts = [
            defaults.render_named_prompt(default_step.phase_prompt_id),
            "",
            "Task:",
            task_prompt,
        ]
        if retry_context:
            prompt_parts.extend(["", "Retry context:", retry_context])
        else:
            prompt_parts.extend(["", "Execution profile:", *[f"- {rule}" for rule in profile.command_rules]])
        steps.append(
            WorkflowStepDefinition(
                step_id=default_step.step_id,
                kind="agent",
                role_id=default_step.role_id,
                fork_from=default_step.fork_from,
                context_mode=default_step.context_mode,
                requires_plan_review=default_step.requires_plan_review,
                prompt="\n".join(part for part in prompt_parts if part),
            )
        )
    return WorkflowDefinition(workflow_id=workflow.workflow_id, steps=tuple(steps)), by_id


def _step_artifact(default_step: DefaultWorkflowStep, result: StepResult, input_prompt: str) -> SolverStepArtifact:
    output_json = dict(result.output_json)
    execution_receipt = dict(result.execution_receipt)
    changed_files_raw = output_json.get("changed_files")
    changed_files = (
        tuple(str(path) for path in changed_files_raw) if isinstance(changed_files_raw, list | tuple) else ()
    )
    return SolverStepArtifact(
        step_id=default_step.step_id,
        role_id=default_step.role_id,
        phase_prompt_id=default_step.phase_prompt_id,
        effort=default_step.effort,
        read_mode_hint=default_step.read_mode_hint,
        status=result.status,
        input_prompt=input_prompt,
        output=str(result.output),
        output_json=output_json,
        execution_receipt=execution_receipt,
        duration_seconds=result.duration_seconds,
        cost_usd=result.cost_usd,
        input_tokens=_receipt_int(execution_receipt, "input_tokens"),
        output_tokens=_receipt_int(execution_receipt, "output_tokens"),
        cache_creation_input_tokens=_receipt_int(execution_receipt, "cache_write_input_tokens"),
        cache_read_input_tokens=_receipt_int(execution_receipt, "cache_read_input_tokens"),
        changed_files=changed_files,
    )


def _parent_step_history(
    *,
    default_step: DefaultWorkflowStep,
    step_histories: dict[str, tuple[dict[str, str], ...]],
    prior_attempt_history: tuple[dict[str, str], ...],
) -> tuple[dict[str, str], ...]:
    if default_step.context_mode == "fresh":
        return ()
    if default_step.fork_from:
        inherited = step_histories.get(default_step.fork_from)
        if inherited is not None:
            return inherited
    return prior_attempt_history


def _compose_agent_prompt(
    *,
    stem_prompt: str,
    current_prompt: str,
    transcript: tuple[dict[str, str], ...],
) -> str:
    return compile_child_prompt(
        stem_prompt=stem_prompt,
        current_prompt=current_prompt,
        transcript=transcript,
    ).prompt


def _format_transcript(transcript: tuple[dict[str, str], ...]) -> str:
    return format_transcript(transcript)


def _raw_output_text(raw_result: Any) -> str:
    if isinstance(raw_result, StepResult):
        return str(raw_result.output)
    if isinstance(raw_result, dict):
        if "output" in raw_result:
            return str(raw_result.get("output") or "")
        if isinstance(raw_result.get("content"), str):
            return str(raw_result["content"])
        return json.dumps(raw_result, sort_keys=True)
    return str(raw_result)


def _step_history_from_attempt(
    previous_attempt: BenchmarkAttempt | None,
) -> tuple[dict[str, str], ...]:
    if previous_attempt is None:
        return ()
    history: list[dict[str, str]] = []
    for artifact in previous_attempt.step_artifacts:
        history.append(
            {
                "step_id": artifact.step_id,
                "phase_prompt_id": artifact.phase_prompt_id,
                "input_prompt": artifact.input_prompt,
                "output": artifact.output,
            }
        )
    return tuple(history)


def _parse_review_verdict(result: StepResult | None) -> dict[str, Any]:
    if result is None:
        return {"verdict": "NEEDS_FIX", "checklist": [], "missing": ["review step missing"]}
    if {"verdict", "checklist", "missing"} <= set(result.output_json):
        verdict = dict(result.output_json)
    else:
        verdict = _parse_json_block(str(result.output))
    if "verdict" not in verdict:
        verdict["verdict"] = "NEEDS_FIX"
    if "checklist" not in verdict:
        verdict["checklist"] = []
    if "missing" not in verdict:
        verdict["missing"] = ["ambiguous review evidence"]
    verdict["verdict"] = str(verdict["verdict"]).upper()
    return verdict


def _parse_json_block(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_solver_execution_route(
    *,
    task_prompt: str,
    defaults: DefaultRegistry,
    profile_id: str,
    route_mode: str,
    provider: str | None,
    model: str | None,
    runner: str | None,
    workspace_root: Path | None,
) -> tuple[OwnedRouteDecision | None, str, str, str, str]:
    profile = defaults.benchmark_profiles[profile_id]
    role_id = profile.role_id
    host_agent = _detect_solver_host_agent()
    host_model = normalize_model_for_host(
        host_agent,
        resolve_host_model(
            host_agent,
            role_id,
            workspace_root=workspace_root,
            fallback=None,
        ),
    )
    legacy_model = model if model is not None else (host_model or "")
    legacy_runner = runner or host_agent
    if route_mode == "native":
        return None, _provider_for_model(legacy_model), legacy_runner, legacy_model, ""
    if route_mode == "explicit" or provider:
        decision = select_owned_route(
            default_store_root(),
            OwnedRouteRequest(
                tool_name="agent",
                task_text=task_prompt,
                mode="explicit",
                provider=(provider or "").strip(),
                model=(model or "").strip(),
                runner=(runner or "").strip(),
                host_agent=_detect_solver_host_agent(),
                session_state={"expected_input_tokens": max(1000, len(task_prompt) // 4)},
            ),
        )
        return decision, decision.provider, decision.runner, decision.model, decision.transport
    try:
        decision = select_owned_route(
            default_store_root(),
            OwnedRouteRequest(
                tool_name="agent",
                task_text=task_prompt,
                mode="auto",
                provider=(provider or "").strip(),
                model=(model or "").strip(),
                runner=(runner or "").strip(),
                host_agent=_detect_solver_host_agent(),
                session_state={"expected_input_tokens": max(1000, len(task_prompt) // 4)},
            ),
        )
        return decision, decision.provider, decision.runner, decision.model, decision.transport
    except (RouteConfigError, NoFeasibleRouteError):
        raise


def _default_step_executor(
    *, repo_root: Path, route_decision: OwnedRouteDecision | None, runner: str, model: str
) -> Any:
    def _execute(
        step: DefaultWorkflowStep,
        prompt: str,
        context: WorkflowContextState,
        _attempt_number: int,
    ) -> dict[str, Any]:
        compiled_prompt = compile_prompt_text(prompt)
        spawn_plan = context.spawn_plan_for_step(step.step_id)
        cache_policy: OwnedCachePolicy = (
            "fresh"
            if str(spawn_plan.get("cache_policy") or getattr(step, "context_mode", "inherit")) == "fresh"
            else "inherit"
        )
        spawn_envelope = build_spawn_envelope(
            step_id=step.step_id,
            role_id=str(getattr(step, "role_id", "") or "general"),
            compiled_prompt=compiled_prompt,
            spawn_group_id=str(spawn_plan.get("spawn_group_id") or ""),
            cache_scope_id=str(spawn_plan.get("cache_scope_id") or ""),
            cache_policy=cache_policy,
        )
        if route_decision is not None:
            affinity_state = (
                latest_cache_affinity(context.step_results, context.step_order) if cache_policy == "inherit" else {}
            )
            try:
                execution = execute_owned_prompt(
                    spawn_envelope.prompt,
                    root=default_store_root(),
                    tool_name="agent",
                    task_text=spawn_envelope.prompt,
                    decision=route_decision,
                    host_agent=_detect_solver_host_agent(),
                    session_state={
                        "workflow_step": step.step_id,
                        "expected_input_tokens": max(1000, len(spawn_envelope.prompt) // 4),
                        "session_phase": step.step_id,
                        "spawn_group_id": spawn_envelope.spawn_group_id,
                        "cache_scope_id": spawn_envelope.cache_scope_id,
                        **cache_affinity_hint({"cache_affinity": affinity_state}),
                    },
                    allow_fallback=route_decision.mode == "auto",
                    cache_policy=cache_policy,
                    compiled_prompt=compiled_prompt.to_dict(),
                    spawn_metadata=spawn_envelope.to_dict(),
                )
            except OwnedExecutionError as exc:
                return {
                    "status": "failed",
                    "output": "",
                    "output_json": {},
                    "execution_receipt": exc.receipt.to_dict(),
                    "duration_seconds": exc.receipt.duration_seconds,
                    "cost_usd": exc.receipt.cost_usd,
                    "error": str(exc),
                }
            return {
                "status": "done",
                "output": execution.output,
                "output_json": _parse_json_block(execution.output),
                "execution_receipt": execution.receipt.to_dict(),
                "duration_seconds": execution.receipt.duration_seconds,
                "cost_usd": execution.receipt.cost_usd,
            }
        lane_key = ":".join(part for part in (spawn_envelope.spawn_group_id, spawn_envelope.role_id) if part)
        observed_lane = context.observed_host_lane(lane_key) if lane_key else {}
        selected_runner = str(observed_lane.get("runner") or runner)
        selected_model = str(observed_lane.get("model") or model)
        if lane_key and not observed_lane:
            context.record_host_lane(lane_key, {"runner": selected_runner, "model": selected_model})
        command = resolve_swarm_runner_command(
            runner=selected_runner,
            runner_model=selected_model,
            runner_args=(),
            child_command=(),
            prompt_template=prompt,
        )
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        duration_seconds = time.perf_counter() - started
        output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            error = (completed.stderr or output or f"{runner} exited with {completed.returncode}").strip()
            return {
                "status": "failed",
                "output": output,
                "output_json": {},
                "execution_receipt": _native_solver_execution_receipt(
                    runner=selected_runner,
                    model=selected_model,
                    status="failed",
                    duration_seconds=duration_seconds,
                    observed_fields=_observed_host_fields(
                        spawn_envelope=spawn_envelope.to_dict(),
                        selected_runner=selected_runner,
                        selected_model=selected_model,
                    ),
                    unverified_fields=_unverified_host_fields(selected_model=selected_model),
                    error=error,
                ),
                "error": error,
            }
        return {
            "status": "done",
            "output": output,
            "output_json": _parse_json_block(output),
            "execution_receipt": _native_solver_execution_receipt(
                runner=selected_runner,
                model=selected_model,
                role_id=step.role_id,
                compiled_prompt=compiled_prompt,
                spawn_envelope=spawn_envelope.to_dict(),
                status="done",
                duration_seconds=duration_seconds,
                observed_fields=_observed_host_fields(
                    spawn_envelope=spawn_envelope.to_dict(),
                    selected_runner=selected_runner,
                    selected_model=selected_model,
                ),
                unverified_fields=_unverified_host_fields(selected_model=selected_model),
            ),
        }

    return _execute


def _native_solver_execution_receipt(
    *,
    runner: str,
    model: str,
    status: str,
    role_id: str = "",
    compiled_prompt: Any | None = None,
    spawn_envelope: dict[str, Any] | None = None,
    duration_seconds: float = 0.0,
    observed_fields: tuple[str, ...] = (),
    unverified_fields: tuple[str, ...] = (),
    error: str = "",
) -> dict[str, Any]:
    provider = _provider_for_model(model)
    compiled = compiled_prompt if hasattr(compiled_prompt, "stable_prefix_hash") else None
    envelope = dict(spawn_envelope or {})
    requested_fields = tuple(str(field) for field in envelope.get("requested_fields", ()))
    honored_fields = ("prompt",)
    dropped_fields = tuple(field for field in requested_fields if field not in honored_fields)
    return {
        "status": status,
        "mode": "native",
        "role_id": role_id,
        "selected_provider": provider,
        "selected_model": model,
        "selected_runner": runner,
        "selected_transport": "host-cli",
        "executed_provider": "",
        "executed_model": "",
        "executed_runner": runner if status == "done" else "",
        "executed_transport": "host-cli" if status == "done" else "",
        "request_id": "",
        "duration_seconds": duration_seconds,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "modeled_cache_read_input_tokens": 0,
        "stable_prefix_hash": getattr(compiled, "stable_prefix_hash", ""),
        "stable_prefix_tokens": getattr(compiled, "stable_prefix_tokens", 0),
        "dynamic_tokens": getattr(compiled, "dynamic_tokens", 0),
        "prefix_invalidated_reason": "cache_policy_fresh" if str(envelope.get("cache_policy") or "") == "fresh" else "",
        "cache_evidence": "hint_only" if getattr(compiled, "stable_prefix_hash", "") else "none",
        "cache_capability": "hint_only" if getattr(compiled, "stable_prefix_hash", "") else "none",
        "spawn_group_id": str(envelope.get("spawn_group_id") or ""),
        "cache_scope_id": str(envelope.get("cache_scope_id") or ""),
        "cache_policy": str(envelope.get("cache_policy") or "inherit"),
        "eligible_for_reuse": bool(
            getattr(compiled, "stable_prefix_hash", "") and str(envelope.get("cache_policy") or "inherit") != "fresh"
        ),
        "reuse_observed": False,
        "spawn_latency_ms": int(duration_seconds * 1000),
        "requested_fields": list(requested_fields),
        "honored_fields": list(observed_fields or honored_fields),
        "dropped_fields": list(dropped_fields),
        "observed_fields": list(observed_fields),
        "unverified_fields": list(unverified_fields),
        "observation_mode": "runtime-observed",
        "cost_usd": 0.0,
        "rerouted": False,
        "attempts": [],
        "error": error,
    }


def _observed_host_fields(
    *,
    spawn_envelope: dict[str, Any],
    selected_runner: str,
    selected_model: str,
) -> tuple[str, ...]:
    observed = ["prompt", "cache_policy", "spawn_group_id", "cache_scope_id"]
    if str(spawn_envelope.get("role_id") or "").strip():
        observed.append("role_id")
    if selected_runner:
        observed.append("selected_runner")
    if selected_model:
        observed.append("selected_model")
    return tuple(observed)


def _unverified_host_fields(*, selected_model: str) -> tuple[str, ...]:
    fields = ["executed_provider", "executed_transport", "reuse_observed"]
    if selected_model:
        fields.append("executed_model")
    return tuple(fields)


def _detect_solver_host_agent() -> str:
    if os.environ.get("CLAUDE_CODE"):
        return "claude"
    if os.environ.get("GITHUB_COPILOT_SESSION_ID") or os.environ.get("COPILOT_CLI"):
        return "copilot"
    if os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX_CLI"):
        return "codex"
    return ""


def _provider_for_model(model_id: str) -> str:
    normalized = model_id.strip().lower()
    if normalized.startswith("claude"):
        return "anthropic"
    if normalized.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    if normalized.startswith("gemini"):
        return "google"
    return ""


def _receipt_int(receipt: dict[str, Any], key: str) -> int:
    value = receipt.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return int(max(0.0, value))
    return 0


__all__ = [
    "BenchmarkAttempt",
    "HarnessFeedback",
    "SolverEvent",
    "SolverRunArtifact",
    "SolverStepArtifact",
    "WrittenSolverArtifacts",
    "build_retry_context",
    "run_benchmark_solver",
    "write_solver_artifacts",
]
