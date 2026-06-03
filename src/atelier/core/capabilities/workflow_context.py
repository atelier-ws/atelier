from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_FULL_REF_PATTERN = re.compile(r"^\{\{\s*steps\.([A-Za-z0-9_\-]+)\.(output|output_json(?:\.[A-Za-z0-9_\-]+)*)\s*\}\}$")
_ANY_REF_PATTERN = re.compile(r"\{\{\s*steps\.[A-Za-z0-9_\-]+\.(?:output|output_json(?:\.[A-Za-z0-9_\-]+)*)\s*\}\}")


@dataclass(frozen=True)
class StepResult:
    step_id: str
    kind: str
    status: str
    output: Any = ""
    output_json: dict[str, Any] = field(default_factory=dict)
    execution_receipt: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "status": self.status,
            "output": self.output,
            "output_json": copy.deepcopy(self.output_json),
            "execution_receipt": copy.deepcopy(self.execution_receipt),
            "duration_seconds": self.duration_seconds,
            "cost_usd": self.cost_usd,
            "error": self.error,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> StepResult:
        raw_output_json = raw.get("output_json")
        output_json: dict[str, Any] = dict(raw_output_json) if isinstance(raw_output_json, dict) else {}
        raw_execution_receipt = raw.get("execution_receipt")
        execution_receipt = dict(raw_execution_receipt) if isinstance(raw_execution_receipt, dict) else {}
        return cls(
            step_id=str(raw.get("step_id") or "").strip(),
            kind=str(raw.get("kind") or "").strip(),
            status=str(raw.get("status") or "").strip() or "pending",
            output=copy.deepcopy(raw.get("output")),
            output_json=copy.deepcopy(output_json),
            execution_receipt=copy.deepcopy(execution_receipt),
            duration_seconds=float(raw.get("duration_seconds") or 0.0),
            cost_usd=float(raw.get("cost_usd") or 0.0),
            error=str(raw.get("error") or "").strip(),
        )


@dataclass
class WorkflowContextState:
    run_id: str = ""
    status: str = "idle"
    definition_hash: str = ""
    step_results: dict[str, StepResult] = field(default_factory=dict)
    step_order: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "definition_hash": self.definition_hash,
            "step_results": {step_id: result.to_dict() for step_id, result in self.step_results.items()},
            "step_order": list(self.step_order),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> WorkflowContextState:
        data = raw if isinstance(raw, Mapping) else {}
        raw_results = data.get("step_results")
        step_results = (
            {
                str(step_id): StepResult.from_mapping(result)
                for step_id, result in raw_results.items()
                if isinstance(step_id, str) and isinstance(result, Mapping)
            }
            if isinstance(raw_results, Mapping)
            else {}
        )
        step_order = (
            [str(step_id) for step_id in data.get("step_order", []) if str(step_id).strip()]
            if isinstance(data.get("step_order"), list)
            else []
        )
        return cls(
            run_id=str(data.get("run_id") or "").strip(),
            status=str(data.get("status") or "").strip() or "idle",
            definition_hash=str(data.get("definition_hash") or "").strip(),
            step_results=step_results,
            step_order=step_order,
        )

    def record_step_result(self, result: StepResult) -> None:
        self.step_results[result.step_id] = result
        if result.step_id not in self.step_order:
            self.step_order.append(result.step_id)

    def fork_step_context(self, step_id: str) -> dict[str, Any]:
        result = self.step_results.get(step_id)
        if result is None:
            raise ValueError(f"unknown fork source: {step_id}")
        return copy.deepcopy(result.to_dict())

    def resolve_reference(self, reference: str) -> Any:
        match = _FULL_REF_PATTERN.fullmatch(reference.strip())
        if match is None:
            raise ValueError(f"unsupported step reference: {reference}")
        step_id, path = match.groups()
        result = self.step_results.get(step_id)
        if result is None or result.status != "done":
            raise ValueError(f"step output not available: {step_id}")
        if path == "output":
            return copy.deepcopy(result.output)
        current: Any = copy.deepcopy(result.output_json)
        for part in path.split(".")[1:]:
            if not isinstance(current, Mapping) or part not in current:
                raise ValueError(f"missing step output path: {reference}")
            current = current[part]
        return copy.deepcopy(current)

    def render_value(self, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if _FULL_REF_PATTERN.fullmatch(stripped):
                return self.resolve_reference(stripped)
            if _ANY_REF_PATTERN.search(value):
                raise ValueError("workflow templates only support full-value substitutions")
            return value
        if isinstance(value, list):
            return [self.render_value(item) for item in value]
        if isinstance(value, tuple):
            return [self.render_value(item) for item in value]
        if isinstance(value, Mapping):
            return {str(key): self.render_value(item) for key, item in value.items()}
        return value


__all__ = ["StepResult", "WorkflowContextState"]
