"""Phase-linear runner for owned agent sessions.

Runs Survey→Plan→Implement as one growing conversation, placing provider-aware
cache breakpoints so each phase can cache-hit the previous phase's context:

- Anthropic: explicit ``cache_control: {type: ephemeral}`` blocks on the system
  message and after Survey's assistant response.
- OpenAI: automatic prefix caching (no markers needed — stable prefix + seed).
- Gemini: server-side context cache (``cachedContent``) passed in ``extra_body``.
- Others via litellm: stable prefix only, no explicit caching markers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from atelier.core.capabilities.owned_agent_session.receipt import PhaseTokens, SessionReceipt
from atelier.core.capabilities.owned_agent_session.session import OwnedAgentSession
from atelier.core.capabilities.owned_agent_session.stem_prompt import STEM_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_SURVEY_PROMPT = """\
Phase: Survey

Read the relevant files and understand the current codebase state. \
Focus on what already exists that is relevant to the task. \
Be thorough — the Plan phase will build on your findings here."""

_PLAN_PROMPT = """\
Phase: Plan

Based on your survey above, outline a precise implementation plan. \
List the files to change and what to do in each. \
Be specific — the Implement phase will execute this plan exactly."""

_IMPLEMENT_PROMPT = """\
Phase: Implement

Execute the plan you described above. \
Make the file edits. Be precise and minimal."""


def _provider_cache_style(provider: str) -> str:
    """Return the cache-control strategy for *provider*.

    Returns one of: ``"anthropic"``, ``"openai"``, ``"gemini"``, ``"none"``.
    """
    p = provider.lower()
    if "anthropic" in p:
        return "anthropic"
    if "bedrock" in p:
        # Bedrock Claude models support the same cache_control API
        return "anthropic"
    if "openai" in p or "azure" in p:
        # Azure OpenAI has automatic prefix caching like OpenAI
        return "openai"
    if "gemini" in p or "google" in p or "vertex" in p:
        return "gemini"
    return "none"


def _system_message(provider: str) -> dict[str, Any]:
    """Build the stable system message.

    Anthropic gets ``cache_control`` embedded in the content list so
    ``_apply_cache_control`` in litellm_client is a no-op (content is already a
    list, not a string — the existing guard skips double-patching).
    All other providers receive a plain string system message.
    """
    cache_style = _provider_cache_style(provider)
    if cache_style == "anthropic":
        return {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": STEM_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    return {"role": "system", "content": STEM_SYSTEM_PROMPT}


def _assistant_with_breakpoint(content: str, *, provider: str) -> dict[str, Any]:
    """Return an assistant message; Anthropic gets an ephemeral breakpoint."""
    if _provider_cache_style(provider) == "anthropic":
        return {
            "role": "assistant",
            "content": [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}],
        }
    return {"role": "assistant", "content": content}


@dataclass
class PhaseResult:
    phase: str
    content: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


def _call_llm(
    messages: list[dict[str, Any]],
    *,
    model: str,
    provider: str,
    gemini_cached_content: str | None = None,
) -> tuple[str, int, int, int, int]:
    """Call the LLM with provider-aware caching and return a 5-tuple.

    Returns ``(content, input_tokens, output_tokens, cache_read, cache_write)``.

    - Anthropic: ``chat_with_result`` (``cache_control`` blocks already in messages).
    - OpenAI: litellm directly with ``seed=42`` for deterministic prefix reuse
      (automatic prefix caching handles the rest — no explicit markers needed).
    - Gemini: litellm with ``extra_body={"cachedContent": name}`` when a context
      cache has been created for this session.
    - Others: litellm directly, stable prefix only.
    """
    cache_style = _provider_cache_style(provider)

    if cache_style == "anthropic":
        from atelier.infra.internal_llm.litellm_client import chat_with_result

        result = chat_with_result(messages, model=model)
        return (
            result.content,
            result.input_tokens,
            result.output_tokens,
            result.cache_read_input_tokens,
            result.cache_write_input_tokens,
        )

    # Non-Anthropic: call litellm directly with provider-specific parameters
    try:
        import litellm as _litellm
    except ImportError as exc:
        raise RuntimeError("litellm is required for non-Anthropic providers") from exc

    kwargs: dict[str, Any] = {"model": model, "messages": messages}

    if cache_style == "openai":
        # Seed stabilises prefix for OpenAI automatic prefix caching
        kwargs["seed"] = 42

    if cache_style == "gemini" and gemini_cached_content:
        kwargs["extra_body"] = {"cachedContent": gemini_cached_content}

    try:
        response = _litellm.completion(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"LLM call failed ({provider}/{model}): {exc}") from exc

    usage = getattr(response, "usage", None)
    content_text: str = ""
    choices = getattr(response, "choices", [])
    if choices:
        msg = getattr(choices[0], "message", None)
        content_text = str(getattr(msg, "content", "") or "")

    def _tok(attr: str) -> int:
        return int(getattr(usage, attr, 0) or 0)

    return (
        content_text,
        _tok("prompt_tokens"),
        _tok("completion_tokens"),
        # Gemini / OpenAI surface cached tokens differently; litellm normalises both
        _tok("cache_read_input_tokens") or _tok("cached_tokens"),
        _tok("cache_write_input_tokens") or _tok("cache_creation_input_tokens"),
    )


def run_phase_linear(
    session: OwnedAgentSession,
    task: str,
    *,
    dry_run: bool = False,
    gemini_cached_content: str | None = None,
) -> SessionReceipt:
    """Run Survey→Plan→Implement as one phase-linear conversation.

    Cache breakpoints (provider-specific):
    - System message: Anthropic gets ``cache_control: ephemeral``; others get
      a plain system string (Gemini uses ``cachedContent`` instead).
    - Post-Survey assistant response: Anthropic gets a second breakpoint so Plan
      cache-hits Survey's output.  OpenAI/Gemini rely on stable-prefix semantics.

    Args:
        session: The ``OwnedAgentSession`` (provider, model, phase_linear already set).
        task: The task description from the user.
        dry_run: If True, skip the Implement phase.
        gemini_cached_content: ``cachedContent`` name for Gemini context cache.
    """
    receipt = SessionReceipt(
        session_id=session.session_id,
        provider=session.provider,
        model=session.model,
    )

    working: list[dict[str, Any]] = [_system_message(session.provider)]
    phases = ["survey", "plan"] + ([] if dry_run else ["implement"])
    phase_prompts = {
        "survey": f"Task: {task}\n\n{_SURVEY_PROMPT}",
        "plan": _PLAN_PROMPT,
        "implement": _IMPLEMENT_PROMPT,
    }

    for phase in phases:
        prompt = phase_prompts[phase]
        working.append({"role": "user", "content": prompt})
        session.add_user_turn(prompt)
        session.current_phase = phase

        logger.debug("phase=%s provider=%s model=%s msgs=%d", phase, session.provider, session.model, len(working))

        content, inp, out, cr, cw = _call_llm(
            working,
            model=session.model,
            provider=session.provider,
            gemini_cached_content=gemini_cached_content,
        )

        # After Survey: mark assistant response with breakpoint (Anthropic) or plain
        mark = phase == "survey" and session.phase_linear
        if mark:
            turn = _assistant_with_breakpoint(content, provider=session.provider)
            working.append(turn)
            session.add_assistant_turn(content, mark_breakpoint=_provider_cache_style(session.provider) == "anthropic")
        else:
            working.append({"role": "assistant", "content": content})
            session.add_assistant_turn(content, mark_breakpoint=False)

        receipt.phases.append(
            PhaseTokens(
                phase=phase,
                input_tokens=inp,
                output_tokens=out,
                cache_read_tokens=cr,
                cache_write_tokens=cw,
            )
        )

    return receipt


def run_single_shot(
    session: OwnedAgentSession,
    task: str,
    *,
    dry_run: bool = False,
    gemini_cached_content: str | None = None,
) -> SessionReceipt:
    """Run a single-turn owned session (no phase-linear split)."""
    receipt = SessionReceipt(
        session_id=session.session_id,
        provider=session.provider,
        model=session.model,
    )
    messages: list[dict[str, Any]] = [
        _system_message(session.provider),
        {"role": "user", "content": task},
    ]
    session.add_user_turn(task)

    if dry_run:
        receipt.phases.append(PhaseTokens(phase="dry_run"))
        return receipt

    content, inp, out, cr, cw = _call_llm(
        messages,
        model=session.model,
        provider=session.provider,
        gemini_cached_content=gemini_cached_content,
    )
    session.add_assistant_turn(content)
    receipt.phases.append(
        PhaseTokens(
            phase="single",
            input_tokens=inp,
            output_tokens=out,
            cache_read_tokens=cr,
            cache_write_tokens=cw,
        )
    )
    return receipt


__all__ = ["PhaseResult", "_provider_cache_style", "run_phase_linear", "run_single_shot"]
