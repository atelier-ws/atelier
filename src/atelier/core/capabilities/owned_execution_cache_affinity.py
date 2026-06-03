from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from atelier.core.capabilities.model_routing.cache_cost import cache_eviction_cost_usd
from atelier.core.capabilities.model_routing.stickiness import (
    DEFAULT_STICKINESS_WINDOW,
    decrement_stickiness,
    start_stickiness,
    stickiness_remaining,
)
from atelier.core.capabilities.prefix_cache.planner import PrefixCachePlan, PrefixCachePlanner
from atelier.core.capabilities.pricing import get_model_pricing
from atelier.core.capabilities.prompt_compilation.models import BlockKind, PromptBlock, Stability


def build_cache_affinity_state(
    *,
    prompt: str,
    provider: str,
    model: str,
    transport: str,
    prior_state: Mapping[str, Any] | None = None,
    actual_cache_read_input_tokens: int = 0,
    actual_cache_write_input_tokens: int = 0,
) -> dict[str, Any]:
    previous = dict(prior_state or {})
    previous_plan = _plan_from_state(previous)
    current_plan = _plan_prompt(prompt, previous_plan)
    same_route = _same_route(previous, provider=provider, model=model, transport=transport)
    has_actual_cache = actual_cache_read_input_tokens > 0 or actual_cache_write_input_tokens > 0
    modeled_cache_read = current_plan.prefix_tokens if same_route and current_plan.prefix_tokens > 0 else 0
    cache_evidence = "actual" if has_actual_cache else ("modeled" if modeled_cache_read > 0 else "none")
    eviction_cost = _eviction_cost(previous_plan, current_plan, model=model)

    if has_actual_cache:
        sticky = start_stickiness(DEFAULT_STICKINESS_WINDOW).remaining_tool_calls
    elif same_route and stickiness_remaining(previous.get("stickiness_remaining")) > 0:
        sticky = decrement_stickiness(stickiness_remaining(previous.get("stickiness_remaining"))).remaining_tool_calls
    elif current_plan.prefix_tokens > 0:
        sticky = start_stickiness(DEFAULT_STICKINESS_WINDOW).remaining_tool_calls
    else:
        sticky = 0

    prefix_hash = current_plan.prefix_hash if current_plan.prefix_tokens > 0 else ""
    invalidated_reason = (
        current_plan.invalidated_reason if current_plan.invalidated_reason and previous_plan.prefix_tokens > 0 else ""
    )
    return {
        "provider": provider,
        "model": model,
        "transport": transport,
        "stable_prefix_hash": prefix_hash,
        "stable_prefix_tokens": current_plan.prefix_tokens,
        "dynamic_tokens": current_plan.dynamic_tokens,
        "prefix_invalidated_reason": invalidated_reason,
        "cache_evidence": cache_evidence,
        "cache_read_input_tokens": actual_cache_read_input_tokens,
        "cache_write_input_tokens": actual_cache_write_input_tokens,
        "modeled_cache_read_input_tokens": modeled_cache_read if not has_actual_cache else 0,
        "eviction_cost_usd": eviction_cost,
        "stickiness_remaining": sticky,
    }


def cache_affinity_for_route(session_state: Mapping[str, Any]) -> dict[str, Any]:
    raw = session_state.get("cache_affinity")
    return dict(raw) if isinstance(raw, Mapping) else {}


def cache_affinity_hint(session_state: Mapping[str, Any]) -> dict[str, Any]:
    affinity = cache_affinity_for_route(session_state)
    return {
        "cache_affinity": affinity,
        "cache_affinity_provider": str(affinity.get("provider") or ""),
        "cache_affinity_model": str(affinity.get("model") or ""),
        "cache_affinity_transport": str(affinity.get("transport") or ""),
        "cache_eviction_cost_usd": float(affinity.get("eviction_cost_usd") or 0.0),
        "cache_affinity_stickiness_remaining": stickiness_remaining(affinity.get("stickiness_remaining")),
        "cache_affinity_warm": bool(
            str(affinity.get("cache_evidence") or "").strip() in {"actual", "modeled"}
            and affinity.get("stable_prefix_hash")
        ),
    }


def latest_cache_affinity(step_results: Mapping[str, Any], step_order: list[str] | tuple[str, ...]) -> dict[str, Any]:
    for step_id in reversed(step_order):
        result = step_results.get(step_id)
        receipt = getattr(result, "execution_receipt", None)
        if isinstance(receipt, Mapping):
            affinity = receipt.get("cache_affinity")
            if isinstance(affinity, Mapping):
                return dict(affinity)
    return {}


def _plan_prompt(prompt: str, previous_plan: PrefixCachePlan | None) -> PrefixCachePlan:
    stable_prefix, dynamic_tail = _split_prompt(prompt)
    if not stable_prefix:
        tail_tokens = max(0, len(dynamic_tail) // 4)
        return PrefixCachePlan(
            static_prefix=(),
            dynamic_state=(),
            prefix_hash="",
            prefix_tokens=0,
            dynamic_tokens=tail_tokens,
            total_tokens=tail_tokens,
        )
    blocks = (
        PromptBlock(
            id="owned.stem",
            kind=BlockKind.SYSTEM,
            stability=Stability.STATIC,
            content=stable_prefix,
        ),
        PromptBlock(
            id="owned.turn",
            kind=BlockKind.USER_TASK,
            stability=Stability.TURN,
            content=dynamic_tail or prompt,
        ),
    )
    prior_hash = previous_plan.prefix_hash or None if previous_plan is not None else None
    return PrefixCachePlanner().plan_with_history(blocks, prior_hash)


def _plan_from_state(state: Mapping[str, Any]) -> PrefixCachePlan:
    prefix_hash = str(state.get("stable_prefix_hash") or "")
    prefix_tokens = _safe_int(state.get("stable_prefix_tokens"))
    dynamic_tokens = _safe_int(state.get("dynamic_tokens"))
    return PrefixCachePlan(
        static_prefix=(),
        dynamic_state=(),
        prefix_hash=prefix_hash,
        prefix_tokens=prefix_tokens,
        dynamic_tokens=dynamic_tokens,
        total_tokens=prefix_tokens + dynamic_tokens,
        invalidated_reason=str(state.get("prefix_invalidated_reason") or ""),
    )


def _split_prompt(prompt: str) -> tuple[str, str]:
    for marker in ("Forked conversation transcript:", "Current phase prompt:"):
        if marker in prompt:
            stable, dynamic = prompt.split(marker, 1)
            return stable.strip(), f"{marker}{dynamic}".strip()
    return "", prompt.strip()


def _same_route(state: Mapping[str, Any], *, provider: str, model: str, transport: str) -> bool:
    return (
        str(state.get("provider") or "") == provider
        and str(state.get("model") or "") == model
        and str(state.get("transport") or "") == transport
        and bool(state.get("stable_prefix_hash"))
    )


def _eviction_cost(
    previous_plan: PrefixCachePlan,
    current_plan: PrefixCachePlan,
    *,
    model: str,
) -> float:
    if previous_plan.prefix_tokens <= 0 or current_plan.prefix_tokens <= 0:
        return 0.0
    pricing = get_model_pricing(model)
    return cache_eviction_cost_usd(previous_plan, current_plan, pricing)


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return int(max(0.0, value))
    return 0


__all__ = [
    "build_cache_affinity_state",
    "cache_affinity_for_route",
    "cache_affinity_hint",
    "latest_cache_affinity",
]
