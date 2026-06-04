from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_STEP_KINDS = frozenset({"agent", "tool", "shell"})
SUPPORTED_CONTEXT_MODES = frozenset({"inherit", "fresh"})
SAFE_PARALLEL_TOOL_NAMES = frozenset(
    {
        "read",
        "grep",
        "search",
        "symbols",
        "node",
        "explore",
        "callers",
        "callees",
        "usages",
        "impact",
    }
)
_STEP_REF_PATTERN = re.compile(r"\{\{\s*steps\.([A-Za-z0-9_\-]+)\.(?:output|output_json(?:\.[A-Za-z0-9_\-]+)*)\s*\}\}")


@dataclass(frozen=True)
class WorkflowStepDefinition:
    step_id: str
    kind: str
    role_id: str = ""
    next_steps: tuple[str, ...] = ()
    fork_from: str = ""
    context_mode: str = "inherit"
    parallel_safe: bool = False
    requires_plan_review: bool = False
    prompt: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    output_name: str = ""
    json_output: bool = False
    interactive: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    steps: tuple[WorkflowStepDefinition, ...] = ()


def workflow_step_from_mapping(raw: Mapping[str, Any]) -> WorkflowStepDefinition:
    next_steps_raw = raw.get("next_steps") or ()
    next_steps = (
        tuple(str(step_id) for step_id in next_steps_raw if str(step_id).strip())
        if isinstance(next_steps_raw, list | tuple)
        else ()
    )
    raw_args = raw.get("args")
    args: dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
    return WorkflowStepDefinition(
        step_id=str(raw.get("step_id") or raw.get("id") or "").strip(),
        kind=str(raw.get("kind") or "").strip(),
        role_id=str(raw.get("role_id") or "").strip(),
        next_steps=next_steps,
        fork_from=str(raw.get("fork_from") or "").strip(),
        context_mode=str(raw.get("context_mode") or "inherit").strip() or "inherit",
        parallel_safe=bool(raw.get("parallel_safe", False)),
        requires_plan_review=bool(raw.get("requires_plan_review", False)),
        prompt=str(raw.get("prompt") or "").strip(),
        tool=str(raw.get("tool") or "").strip(),
        args=dict(args),
        command=str(raw.get("command") or "").strip(),
        output_name=str(raw.get("output_name") or "").strip(),
        json_output=bool(raw.get("json_output", False)),
        interactive=bool(raw.get("interactive", False)),
    )


def workflow_definition_from_mapping(raw: Mapping[str, Any]) -> WorkflowDefinition:
    steps_raw = raw.get("steps") or ()
    steps = tuple(workflow_step_from_mapping(step) for step in steps_raw if isinstance(step, Mapping))
    return WorkflowDefinition(
        workflow_id=str(raw.get("workflow_id") or raw.get("id") or "").strip(),
        steps=steps,
    )


def referenced_step_ids(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, str):
        refs.update(match.group(1) for match in _STEP_REF_PATTERN.finditer(value))
        return refs
    if isinstance(value, Mapping):
        for nested in value.values():
            refs.update(referenced_step_ids(nested))
        return refs
    if isinstance(value, list | tuple):
        for nested in value:
            refs.update(referenced_step_ids(nested))
    return refs


def step_is_safe_parallel(step: WorkflowStepDefinition) -> bool:
    if step.kind == "tool":
        if step.interactive:
            return False
        if step.tool == "context":
            return str(step.args.get("mode") or "").strip() == "symbols"
        return step.tool in SAFE_PARALLEL_TOOL_NAMES
    if step.kind == "agent":
        return step.parallel_safe and not step.requires_plan_review
    return False


def step_dependencies(definition: WorkflowDefinition) -> dict[str, set[str]]:
    deps: dict[str, set[str]] = {step.step_id: set() for step in definition.steps}
    for step in definition.steps:
        for next_step in step.next_steps:
            deps.setdefault(next_step, set()).add(step.step_id)
        if step.fork_from:
            deps[step.step_id].add(step.fork_from)
        refs = set()
        refs.update(referenced_step_ids(step.prompt))
        refs.update(referenced_step_ids(step.args))
        refs.update(referenced_step_ids(step.command))
        deps[step.step_id].update(refs)
    return deps


def validate_workflow_definition(definition: WorkflowDefinition) -> WorkflowDefinition:
    if not definition.workflow_id:
        raise ValueError("workflow definition requires workflow_id")
    if not definition.steps:
        raise ValueError("workflow definition requires at least one step")

    seen_ids: set[str] = set()
    step_ids = {step.step_id for step in definition.steps}
    if "" in step_ids:
        raise ValueError("workflow step requires step_id")

    for step in definition.steps:
        if step.step_id in seen_ids:
            raise ValueError(f"duplicate step id: {step.step_id}")
        seen_ids.add(step.step_id)
        if step.kind not in SUPPORTED_STEP_KINDS:
            raise ValueError(f"unsupported step kind: {step.kind}")
        if step.context_mode not in SUPPORTED_CONTEXT_MODES:
            raise ValueError(f"unsupported context mode: {step.context_mode}")
        if step.kind == "agent" and not step.prompt:
            raise ValueError(f"agent step requires prompt: {step.step_id}")
        if step.kind == "tool" and not step.tool:
            raise ValueError(f"tool step requires tool: {step.step_id}")
        if step.kind == "shell" and not step.command:
            raise ValueError(f"shell step requires command: {step.step_id}")
        for next_step in step.next_steps:
            if next_step not in step_ids:
                raise ValueError(f"unknown next step: {next_step}")
            if next_step == step.step_id:
                raise ValueError(f"step cannot point to itself: {step.step_id}")
        if step.fork_from:
            if step.fork_from not in step_ids:
                raise ValueError(f"unknown fork source: {step.fork_from}")
            if step.fork_from == step.step_id:
                raise ValueError(f"step cannot fork from itself: {step.step_id}")
        refs = referenced_step_ids(step.prompt) | referenced_step_ids(step.args) | referenced_step_ids(step.command)
        unknown_refs = sorted(ref for ref in refs if ref not in step_ids)
        if unknown_refs:
            raise ValueError(f"unknown step reference: {', '.join(unknown_refs)}")
        if step.step_id in refs:
            raise ValueError(f"step cannot reference itself: {step.step_id}")

    deps = step_dependencies(definition)
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(step_id: str) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            raise ValueError(f"workflow contains a cycle at step: {step_id}")
        visiting.add(step_id)
        for dep in deps.get(step_id, ()):
            _visit(dep)
        visiting.remove(step_id)
        visited.add(step_id)

    for step in definition.steps:
        _visit(step.step_id)
    return definition


__all__ = [
    "SAFE_PARALLEL_TOOL_NAMES",
    "SUPPORTED_CONTEXT_MODES",
    "SUPPORTED_STEP_KINDS",
    "WorkflowDefinition",
    "WorkflowStepDefinition",
    "referenced_step_ids",
    "step_dependencies",
    "step_is_safe_parallel",
    "validate_workflow_definition",
    "workflow_definition_from_mapping",
    "workflow_step_from_mapping",
]
