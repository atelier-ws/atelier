from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from atelier.core.capabilities.default_definitions import (
    DefaultRegistry,
    DefaultWorkflow,
    DefaultWorkflowStep,
    build_default_registry,
)
from atelier.core.capabilities.host_runners import resolve_swarm_runner_command
from atelier.core.capabilities.workflow_context import StepResult, WorkflowContextState
from atelier.core.capabilities.workflow_runner import WorkflowRunner
from atelier.core.capabilities.workflow_schema import WorkflowDefinition, WorkflowStepDefinition


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
    output: str
    output_json: dict[str, Any]
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    changed_files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "role_id": self.role_id,
            "phase_prompt_id": self.phase_prompt_id,
            "effort": self.effort,
            "read_mode_hint": self.read_mode_hint,
            "status": self.status,
            "output": self.output,
            "output_json": dict(self.output_json),
            "duration_seconds": self.duration_seconds,
            "cost_usd": self.cost_usd,
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
    model: str | None = None,
    runner: str = "claude",
) -> SolverRunArtifact:
    defaults = build_default_registry(repo_root)
    profile = defaults.benchmark_profiles[profile_id]
    workflow = defaults.workflows[profile.workflow_id]
    run_id = uuid.uuid4().hex
    limit = max_attempts if max_attempts is not None else profile.retry_limit
    resolved_model = model or defaults.roles[profile.role_id].model_default
    executor = step_executor or _default_step_executor(
        repo_root=Path.cwd().resolve() if repo_root is None else repo_root,
        runner=runner,
        model=resolved_model,
    )
    events: list[SolverEvent] = [SolverEvent(event="start", run_id=run_id, attempt_number=1)]
    attempts: list[BenchmarkAttempt] = []
    retry_context = ""
    previous_attempt: BenchmarkAttempt | None = None
    final_status = "failed"

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
        task_prompt=task_prompt,
        retry_context=retry_context,
    )

    def agent_executor(
        step: WorkflowStepDefinition,
        rendered_prompt: str,
        context_state: WorkflowContextState,
    ) -> Any:
        default_step = default_steps[step.step_id]
        return step_executor(default_step, rendered_prompt, context_state, attempt_number)

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
        _step_artifact(default_steps[step_id], result.step_results[step_id])
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
        duration_seconds=sum(item.duration_seconds for item in step_artifacts),
        cost_usd=sum(item.cost_usd for item in step_artifacts),
    )


def _build_workflow_definition(
    workflow: DefaultWorkflow,
    *,
    defaults: DefaultRegistry,
    task_prompt: str,
    retry_context: str,
) -> tuple[WorkflowDefinition, dict[str, DefaultWorkflowStep]]:
    steps: list[WorkflowStepDefinition] = []
    by_id: dict[str, DefaultWorkflowStep] = {}
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
        steps.append(
            WorkflowStepDefinition(
                step_id=default_step.step_id,
                kind="agent",
                fork_from=default_step.fork_from,
                prompt="\n".join(part for part in prompt_parts if part),
            )
        )
    return WorkflowDefinition(workflow_id=workflow.workflow_id, steps=tuple(steps)), by_id


def _step_artifact(default_step: DefaultWorkflowStep, result: StepResult) -> SolverStepArtifact:
    output_json = dict(result.output_json)
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
        output=str(result.output),
        output_json=output_json,
        duration_seconds=result.duration_seconds,
        cost_usd=result.cost_usd,
        changed_files=changed_files,
    )


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


def _default_step_executor(*, repo_root: Path, runner: str, model: str) -> Any:
    def _execute(
        _step: DefaultWorkflowStep,
        prompt: str,
        _context: WorkflowContextState,
        _attempt_number: int,
    ) -> dict[str, Any]:
        command = resolve_swarm_runner_command(
            runner=runner,
            runner_model=model,
            runner_args=(),
            child_command=(),
            prompt_template=prompt,
        )
        completed = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            error = (completed.stderr or output or f"{runner} exited with {completed.returncode}").strip()
            return {"status": "failed", "output": output, "output_json": {}, "error": error}
        return {"status": "done", "output": output, "output_json": _parse_json_block(output)}

    return _execute


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
