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


def _system_message() -> dict[str, Any]:
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


def _mark_breakpoint(messages: list[dict[str, Any]], idx: int) -> None:
    """Embed an ephemeral cache_control breakpoint on an assistant message at *idx*."""
    msg = dict(messages[idx])
    content = msg.get("content", "")
    if isinstance(content, str) and content.strip():
        msg["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
        messages[idx] = msg


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
) -> tuple[str, int, int, int, int]:
    """Call litellm and return (content, input, output, cache_read, cache_write)."""
    from atelier.infra.internal_llm.litellm_client import chat_with_result

    result = chat_with_result(messages, model=model)
    return (
        result.content,
        result.input_tokens,
        result.output_tokens,
        result.cache_read_input_tokens,
        result.cache_write_input_tokens,
    )


def run_phase_linear(
    session: OwnedAgentSession,
    task: str,
    *,
    dry_run: bool = False,
) -> SessionReceipt:
    """Run Survey→Plan→Implement as one phase-linear conversation.

    Places ephemeral cache_control breakpoints:
    1. On the system message (stable prefix)
    2. After Survey's assistant response (so Plan cache-hits the survey context)
    """
    receipt = SessionReceipt(
        session_id=session.session_id,
        provider=session.provider,
        model=session.model,
    )

    # Seed the session with a fixed system message (never mutated)
    base_messages: list[dict[str, Any]] = [_system_message()]

    phases = ["survey", "plan"] + ([] if dry_run else ["implement"])
    phase_prompts = {
        "survey": f"Task: {task}\n\n{_SURVEY_PROMPT}",
        "plan": _PLAN_PROMPT,
        "implement": _IMPLEMENT_PROMPT,
    }

    working: list[dict[str, Any]] = list(base_messages)

    for phase in phases:
        prompt = phase_prompts[phase]
        working.append({"role": "user", "content": prompt})
        session.add_user_turn(prompt)
        session.current_phase = phase

        logger.debug("phase=%s model=%s messages=%d", phase, session.model, len(working))

        content, inp, out, cr, cw = _call_llm(working, model=session.model)

        # Mark Survey's assistant response with a breakpoint so Plan cache-hits it
        if phase == "survey" and session.phase_linear:
            working.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            )
            session.add_assistant_turn(content, mark_breakpoint=True)
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
) -> SessionReceipt:
    """Run a single-turn owned session (no phase-linear split)."""
    receipt = SessionReceipt(
        session_id=session.session_id,
        provider=session.provider,
        model=session.model,
    )
    messages: list[dict[str, Any]] = [
        _system_message(),
        {"role": "user", "content": task},
    ]
    session.add_user_turn(task)

    if dry_run:
        receipt.phases.append(PhaseTokens(phase="dry_run"))
        return receipt

    content, inp, out, cr, cw = _call_llm(messages, model=session.model)
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


__all__ = ["PhaseResult", "run_phase_linear", "run_single_shot"]
