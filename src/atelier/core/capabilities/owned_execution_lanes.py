from __future__ import annotations

import inspect
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atelier.core.capabilities.owned_execution_cache_affinity import (
    build_cache_affinity_state,
    cache_affinity_for_route,
)
from atelier.core.capabilities.owned_execution_routing import (
    OwnedCachePolicy,
    OwnedRouteDecision,
    OwnedRouteRequest,
    select_owned_route,
)
from atelier.core.capabilities.workflow_spawn import compile_prompt_text, scope_break_reason
from atelier.infra.internal_llm.exceptions import InternalLLMError
from atelier.infra.internal_llm.litellm_client import chat_with_result as litellm_chat_with_result
from atelier.infra.internal_llm.openai_client import chat_with_result as openai_chat_with_result
from atelier.infra.internal_llm.result import InternalLLMChatResult


@dataclass(frozen=True)
class OwnedExecutionAttempt:
    attempt_index: int
    provider: str
    model: str
    runner: str
    transport: str
    status: str
    request_id: str = ""
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    modeled_cache_read_input_tokens: int = 0
    stable_prefix_hash: str = ""
    stable_prefix_tokens: int = 0
    dynamic_tokens: int = 0
    prefix_invalidated_reason: str = ""
    cache_evidence: str = "none"
    cost_usd: float = 0.0
    error_type: str = ""
    error_message: str = ""
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "provider": self.provider,
            "model": self.model,
            "runner": self.runner,
            "transport": self.transport,
            "status": self.status,
            "request_id": self.request_id,
            "duration_seconds": self.duration_seconds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "modeled_cache_read_input_tokens": self.modeled_cache_read_input_tokens,
            "stable_prefix_hash": self.stable_prefix_hash,
            "stable_prefix_tokens": self.stable_prefix_tokens,
            "dynamic_tokens": self.dynamic_tokens,
            "prefix_invalidated_reason": self.prefix_invalidated_reason,
            "cache_evidence": self.cache_evidence,
            "cost_usd": self.cost_usd,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class OwnedExecutionReceipt:
    status: str
    mode: str
    cache_policy: str
    selected_provider: str
    selected_model: str
    selected_runner: str
    selected_transport: str
    executed_provider: str
    executed_model: str
    executed_runner: str
    executed_transport: str
    request_id: str = ""
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    modeled_cache_read_input_tokens: int = 0
    stable_prefix_hash: str = ""
    stable_prefix_tokens: int = 0
    dynamic_tokens: int = 0
    prefix_invalidated_reason: str = ""
    cache_evidence: str = "none"
    cache_capability: str = "none"
    spawn_group_id: str = ""
    cache_scope_id: str = ""
    eligible_for_reuse: bool = False
    reuse_observed: bool = False
    spawn_latency_ms: int = 0
    requested_fields: tuple[str, ...] = ()
    honored_fields: tuple[str, ...] = ()
    dropped_fields: tuple[str, ...] = ()
    scope_break_reason: str = ""
    cost_usd: float = 0.0
    rerouted: bool = False
    error: str = ""
    cache_affinity: dict[str, Any] | None = None
    attempts: tuple[OwnedExecutionAttempt, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "cache_policy": self.cache_policy,
            "selected_provider": self.selected_provider,
            "selected_model": self.selected_model,
            "selected_runner": self.selected_runner,
            "selected_transport": self.selected_transport,
            "executed_provider": self.executed_provider,
            "executed_model": self.executed_model,
            "executed_runner": self.executed_runner,
            "executed_transport": self.executed_transport,
            "request_id": self.request_id,
            "duration_seconds": self.duration_seconds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "modeled_cache_read_input_tokens": self.modeled_cache_read_input_tokens,
            "stable_prefix_hash": self.stable_prefix_hash,
            "stable_prefix_tokens": self.stable_prefix_tokens,
            "dynamic_tokens": self.dynamic_tokens,
            "prefix_invalidated_reason": self.prefix_invalidated_reason,
            "cache_evidence": self.cache_evidence,
            "cache_capability": self.cache_capability,
            "spawn_group_id": self.spawn_group_id,
            "cache_scope_id": self.cache_scope_id,
            "eligible_for_reuse": self.eligible_for_reuse,
            "reuse_observed": self.reuse_observed,
            "spawn_latency_ms": self.spawn_latency_ms,
            "requested_fields": list(self.requested_fields),
            "honored_fields": list(self.honored_fields),
            "dropped_fields": list(self.dropped_fields),
            "scope_break_reason": self.scope_break_reason,
            "cost_usd": self.cost_usd,
            "rerouted": self.rerouted,
            "error": self.error,
            "cache_affinity": dict(self.cache_affinity or {}),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


@dataclass(frozen=True)
class OwnedExecutionResult:
    output: str
    receipt: OwnedExecutionReceipt


class OwnedExecutionError(RuntimeError):
    def __init__(self, message: str, *, receipt: OwnedExecutionReceipt) -> None:
        super().__init__(message)
        self.receipt = receipt


def execute_owned_prompt(
    prompt: str,
    *,
    root: Path | str,
    tool_name: str,
    task_text: str,
    decision: OwnedRouteDecision,
    host_agent: str = "",
    session_state: Mapping[str, Any] | None = None,
    allow_fallback: bool = True,
    cache_policy: OwnedCachePolicy = "inherit",
    compiled_prompt: Mapping[str, Any] | None = None,
    spawn_metadata: Mapping[str, Any] | None = None,
) -> OwnedExecutionResult:
    base_state = dict(session_state or {})
    compiled = dict(compiled_prompt) if isinstance(compiled_prompt, Mapping) else compile_prompt_text(prompt).to_dict()
    spawn = dict(spawn_metadata) if isinstance(spawn_metadata, Mapping) else {}
    normalized_cache_policy: OwnedCachePolicy = "fresh" if cache_policy == "fresh" else "inherit"
    prior_affinity = cache_affinity_for_route(base_state) if normalized_cache_policy == "inherit" else {}
    selected = decision
    current = decision
    attempts: list[OwnedExecutionAttempt] = []

    for attempt_index in range(1, 3):
        started = time.perf_counter()
        try:
            response = _execute_transport(
                prompt,
                compiled_prompt=compiled,
                provider=current.provider,
                model=current.model,
                transport=current.transport,
            )
        except InternalLLMError as exc:
            attempts.append(
                OwnedExecutionAttempt(
                    attempt_index=attempt_index,
                    provider=current.provider,
                    model=current.model,
                    runner=current.runner,
                    transport=current.transport,
                    status="failed",
                    duration_seconds=time.perf_counter() - started,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    fallback_reason="provider execution failure" if current.mode == "auto" else "",
                )
            )
            if current.mode != "auto" or not allow_fallback or attempt_index >= 2:
                raise OwnedExecutionError(
                    str(exc),
                    receipt=_failure_receipt(
                        selected=selected,
                        attempts=attempts,
                        cache_policy=normalized_cache_policy,
                    ),
                ) from exc
            next_decision = _fallback_route(
                root=root,
                tool_name=tool_name,
                task_text=task_text,
                failed_provider=current.provider,
                host_agent=host_agent,
                session_state=base_state,
                cache_policy=normalized_cache_policy,
            )
            if next_decision.provider == current.provider and next_decision.model == current.model:
                raise OwnedExecutionError(
                    str(exc),
                    receipt=_failure_receipt(
                        selected=selected,
                        attempts=attempts,
                        cache_policy=normalized_cache_policy,
                    ),
                ) from exc
            current = next_decision
            continue

        duration_seconds = time.perf_counter() - started
        if normalized_cache_policy == "inherit":
            cache_affinity = build_cache_affinity_state(
                prompt=prompt,
                provider=current.provider,
                model=current.model,
                transport=current.transport,
                prior_state=prior_affinity,
                compiled_prompt=compiled,
                cache_scope_id=str(spawn.get("cache_scope_id") or ""),
                spawn_group_id=str(spawn.get("spawn_group_id") or ""),
                actual_cache_read_input_tokens=response.cache_read_input_tokens,
                actual_cache_write_input_tokens=response.cache_write_input_tokens,
            )
        else:
            cache_affinity = _fresh_cache_affinity(
                provider=current.provider,
                model=current.model,
                transport=current.transport,
                actual_cache_read_input_tokens=response.cache_read_input_tokens,
                actual_cache_write_input_tokens=response.cache_write_input_tokens,
            )
        attempts.append(
            OwnedExecutionAttempt(
                attempt_index=attempt_index,
                provider=current.provider,
                model=current.model,
                runner=current.runner,
                transport=current.transport,
                status="done",
                request_id=response.request_id,
                duration_seconds=duration_seconds,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cache_read_input_tokens=response.cache_read_input_tokens,
                cache_write_input_tokens=response.cache_write_input_tokens,
                modeled_cache_read_input_tokens=int(cache_affinity.get("modeled_cache_read_input_tokens") or 0),
                stable_prefix_hash=str(cache_affinity.get("stable_prefix_hash") or ""),
                stable_prefix_tokens=int(cache_affinity.get("stable_prefix_tokens") or 0),
                dynamic_tokens=int(cache_affinity.get("dynamic_tokens") or 0),
                prefix_invalidated_reason=str(cache_affinity.get("prefix_invalidated_reason") or ""),
                cache_evidence=str(cache_affinity.get("cache_evidence") or "none"),
            )
        )
        receipt = OwnedExecutionReceipt(
            status="done",
            mode=selected.mode,
            cache_policy=normalized_cache_policy,
            selected_provider=selected.provider,
            selected_model=selected.model,
            selected_runner=selected.runner,
            selected_transport=selected.transport,
            executed_provider=current.provider,
            executed_model=current.model,
            executed_runner=current.runner,
            executed_transport=current.transport,
            request_id=response.request_id,
            duration_seconds=duration_seconds,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_read_input_tokens=response.cache_read_input_tokens,
            cache_write_input_tokens=response.cache_write_input_tokens,
            modeled_cache_read_input_tokens=int(cache_affinity.get("modeled_cache_read_input_tokens") or 0),
            stable_prefix_hash=str(cache_affinity.get("stable_prefix_hash") or ""),
            stable_prefix_tokens=int(cache_affinity.get("stable_prefix_tokens") or 0),
            dynamic_tokens=int(cache_affinity.get("dynamic_tokens") or 0),
            prefix_invalidated_reason=str(cache_affinity.get("prefix_invalidated_reason") or ""),
            cache_evidence=str(cache_affinity.get("cache_evidence") or "none"),
            cache_capability=str(response.cache_capability or _cache_capability(compiled, current.transport)),
            spawn_group_id=str(spawn.get("spawn_group_id") or ""),
            cache_scope_id=str(spawn.get("cache_scope_id") or ""),
            eligible_for_reuse=bool(compiled.get("stable_prefix_hash") and normalized_cache_policy == "inherit"),
            reuse_observed=response.cache_read_input_tokens > 0,
            spawn_latency_ms=int(duration_seconds * 1000),
            requested_fields=tuple(str(field) for field in spawn.get("requested_fields", ()) if str(field).strip()),
            honored_fields=tuple(str(field) for field in spawn.get("requested_fields", ()) if str(field).strip()),
            dropped_fields=(),
            scope_break_reason=scope_break_reason(
                cache_policy=normalized_cache_policy,
                prior_scope_id=str(prior_affinity.get("cache_scope_id") or ""),
                prior_prefix_hash=str(prior_affinity.get("stable_prefix_hash") or ""),
                current_prefix_hash=str(cache_affinity.get("stable_prefix_hash") or ""),
                selected_model=selected.model,
                executed_model=current.model,
                selected_provider=selected.provider,
                executed_provider=current.provider,
                selected_transport=selected.transport,
                executed_transport=current.transport,
            ),
            rerouted=attempt_index > 1,
            cache_affinity=cache_affinity,
            attempts=tuple(attempts),
        )
        return OwnedExecutionResult(output=response.content, receipt=receipt)

    raise OwnedExecutionError(
        "owned execution ended without a result",
        receipt=_failure_receipt(
            selected=selected,
            attempts=attempts,
            cache_policy=normalized_cache_policy,
        ),
    )


def _execute_transport(
    prompt: str,
    *,
    compiled_prompt: Mapping[str, Any] | None = None,
    provider: str,
    model: str,
    transport: str,
) -> InternalLLMChatResult:
    messages, cache_metadata = _transport_payload(
        prompt, compiled_prompt=compiled_prompt, transport=transport, provider=provider
    )
    if transport == "openai":
        if _supports_cache_metadata(openai_chat_with_result):
            return openai_chat_with_result(messages, model=model, cache_metadata=cache_metadata)
        return openai_chat_with_result(messages, model=model)
    if transport == "litellm":
        if _supports_cache_metadata(litellm_chat_with_result):
            return litellm_chat_with_result(messages, model=model, cache_metadata=cache_metadata)
        return litellm_chat_with_result(messages, model=model)
    raise InternalLLMError(f"provider {provider!r} has no owned execution transport for model {model!r}")


def _fallback_route(
    *,
    root: Path | str,
    tool_name: str,
    task_text: str,
    failed_provider: str,
    host_agent: str,
    session_state: Mapping[str, Any],
    cache_policy: OwnedCachePolicy,
) -> OwnedRouteDecision:
    updated_state = dict(session_state)
    failures = dict(updated_state.get("provider_failures") or {})
    failures[failed_provider] = int(failures.get(failed_provider, 0) or 0) + 1
    updated_state["provider_failures"] = failures
    return select_owned_route(
        root,
        OwnedRouteRequest(
            tool_name=tool_name,
            task_text=task_text,
            mode="auto",
            host_agent=host_agent,
            session_state=updated_state,
            cache_policy=cache_policy,
        ),
    )


def _failure_receipt(
    *,
    selected: OwnedRouteDecision,
    attempts: list[OwnedExecutionAttempt],
    cache_policy: OwnedCachePolicy,
) -> OwnedExecutionReceipt:
    last = attempts[-1] if attempts else None
    return OwnedExecutionReceipt(
        status="failed",
        mode=selected.mode,
        cache_policy=cache_policy,
        selected_provider=selected.provider,
        selected_model=selected.model,
        selected_runner=selected.runner,
        selected_transport=selected.transport,
        executed_provider=last.provider if last is not None else selected.provider,
        executed_model=last.model if last is not None else selected.model,
        executed_runner=last.runner if last is not None else selected.runner,
        executed_transport=last.transport if last is not None else selected.transport,
        request_id=last.request_id if last is not None else "",
        duration_seconds=sum(attempt.duration_seconds for attempt in attempts),
        input_tokens=sum(attempt.input_tokens for attempt in attempts),
        output_tokens=sum(attempt.output_tokens for attempt in attempts),
        cache_read_input_tokens=sum(attempt.cache_read_input_tokens for attempt in attempts),
        cache_write_input_tokens=sum(attempt.cache_write_input_tokens for attempt in attempts),
        modeled_cache_read_input_tokens=sum(attempt.modeled_cache_read_input_tokens for attempt in attempts),
        stable_prefix_hash="",
        stable_prefix_tokens=0,
        dynamic_tokens=0,
        prefix_invalidated_reason="",
        cache_evidence="none",
        cache_capability="none",
        spawn_latency_ms=int(sum(attempt.duration_seconds for attempt in attempts) * 1000),
        cost_usd=sum(attempt.cost_usd for attempt in attempts),
        rerouted=len(attempts) > 1,
        error=last.error_message if last is not None else "",
        attempts=tuple(attempts),
    )


def _fresh_cache_affinity(
    *,
    provider: str,
    model: str,
    transport: str,
    actual_cache_read_input_tokens: int,
    actual_cache_write_input_tokens: int,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "transport": transport,
        "stable_prefix_hash": "",
        "stable_prefix_tokens": 0,
        "dynamic_tokens": 0,
        "prefix_invalidated_reason": "cache_policy_fresh",
        "cache_evidence": "disabled",
        "cache_read_input_tokens": actual_cache_read_input_tokens,
        "cache_write_input_tokens": actual_cache_write_input_tokens,
        "modeled_cache_read_input_tokens": 0,
        "eviction_cost_usd": 0.0,
        "stickiness_remaining": 0,
    }


__all__ = [
    "OwnedExecutionAttempt",
    "OwnedExecutionError",
    "OwnedExecutionReceipt",
    "OwnedExecutionResult",
    "execute_owned_prompt",
]


def _transport_payload(
    prompt: str,
    *,
    compiled_prompt: Mapping[str, Any] | None,
    transport: str,
    provider: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    compiled = dict(compiled_prompt or {})
    stable_prefix = str(compiled.get("stable_prefix") or "").strip()
    dynamic_tail = str(compiled.get("dynamic_tail") or "").strip() or prompt
    cache_metadata: dict[str, Any] = {}
    if stable_prefix:
        messages = [{"role": "system", "content": stable_prefix}, {"role": "user", "content": dynamic_tail}]
        if transport == "openai":
            cache_metadata["prompt_cache_key"] = str(compiled.get("stable_prefix_hash") or "")
        elif transport == "litellm":
            cache_metadata["stable_prefix_hash"] = str(compiled.get("stable_prefix_hash") or "")
    else:
        messages = [{"role": "user", "content": prompt}]
    if provider in {"anthropic", "openai", "google"} and stable_prefix:
        cache_metadata["stable_prefix"] = stable_prefix
        cache_metadata["dynamic_tail"] = dynamic_tail
    return messages, cache_metadata


def _cache_capability(compiled_prompt: Mapping[str, Any], transport: str) -> str:
    if not str(compiled_prompt.get("stable_prefix_hash") or ""):
        return "none"
    return "explicit" if transport == "openai" else "hint_only"


def _supports_cache_metadata(func: Any) -> bool:
    try:
        return "cache_metadata" in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
