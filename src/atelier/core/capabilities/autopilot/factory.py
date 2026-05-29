"""Provider wiring + hook entrypoint for autopilot choreography (M5).

Builds an :class:`AutopilotCapability` with best-effort providers resolved from
the store root + workspace. Every provider is fail-open: if a dependency cannot
be constructed or errors, it yields empty results and the behavior degrades to
a noop rather than raising. Hooks call :func:`run_autopilot_event` and deliver
the result with :func:`emit_action`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .capability import AutopilotCapability
from .models import AutopilotAction, AutopilotConfig, AutopilotEvent

_HOOK_EVENT_NAMES = {
    "session_start": "SessionStart",
    "user_prompt": "UserPromptSubmit",
    "post_edit": "PostToolUse",
}


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no", ""}


def config_from_env() -> AutopilotConfig:
    return AutopilotConfig(
        enabled=_flag("ATELIER_AUTOPILOT", True),
        session_warm=_flag("ATELIER_AUTOPILOT_SESSION_WARM", True),
        scoped_inject=_flag("ATELIER_AUTOPILOT_SCOPED_INJECT", True),
        counterexamples=_flag("ATELIER_AUTOPILOT_COUNTEREXAMPLES", True),
    )


def _lessons_provider(store_root: str) -> Any:
    def fn() -> list[str]:
        try:
            from atelier.core.capabilities.lesson_promotion import LessonPromoterCapability
            from atelier.infra.storage.factory import create_store

            cap = LessonPromoterCapability(create_store(Path(store_root)))
            items = cap.inbox(limit=5)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return []
        out: list[str] = []
        for it in items:
            text = (
                getattr(it, "summary", None)
                or getattr(it, "title", None)
                or getattr(it, "lesson", None)
                or getattr(it, "text", None)
            )
            if text:
                out.append(str(text))
        return out

    return fn


def _scoped_pull_provider(workspace: str) -> Any:
    def fn(prompt: str, files: list[str]) -> Any:
        try:
            from atelier.core.capabilities.code_context import CodeContextEngine
            from atelier.core.capabilities.scoped_context import ScopedContextCapability, Subtask

            engine = CodeContextEngine(Path(workspace))
            cap = ScopedContextCapability(engine)
            return cap.pull(Subtask(description=prompt, affected_paths=list(files), budget_tokens=1200))
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return None

    return fn


def _verify_provider(workspace: str) -> Any:
    def fn(files: list[str]) -> list[Any]:
        try:
            from atelier.core.capabilities.verification import VerifierCapability

            checks: tuple[str, ...] = ("lint",)
            if _flag("ATELIER_AUTOPILOT_TYPECHECK", False):
                checks = (*checks, "typecheck")
            if _flag("ATELIER_AUTOPILOT_TESTS", False):
                checks = (*checks, "tests")
            return VerifierCapability(cwd=workspace).run(scope_files=list(files), checks=checks)
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return []

    return fn


def build_autopilot(*, store_root: str, workspace: str) -> AutopilotCapability:
    return AutopilotCapability(
        config_from_env(),
        lessons_fn=_lessons_provider(store_root),
        scoped_pull_fn=_scoped_pull_provider(workspace),
        verify_fn=_verify_provider(workspace),
    )


def run_autopilot_event(trigger: str, payload: dict[str, Any]) -> AutopilotAction:
    """Resolve roots from env, build the capability, and evaluate one event."""
    try:
        store_root = (
            os.environ.get("ATELIER_ROOT") or os.environ.get("ATELIER_STORE_ROOT") or str(Path.home() / ".atelier")
        )
        workspace = os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()
        cap = build_autopilot(store_root=store_root, workspace=workspace)
        return cap.on_event(AutopilotEvent(trigger, payload))
    except Exception:
        logging.exception("Recovered from broad exception handler")
        return AutopilotAction.noop("error")


def emit_action(trigger: str, action: AutopilotAction) -> None:
    """Write the host's additionalContext payload to stdout (no-op for noop)."""
    if action.kind != "inject" or not action.content:
        return
    hook_event = _HOOK_EVENT_NAMES.get(trigger, "")
    if not hook_event:
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "additionalContext": action.content,
        }
    }
    sys.stdout.write(json.dumps(payload))


def run_and_emit(trigger: str, payload: dict[str, Any]) -> None:
    """Convenience for hooks: evaluate an event and emit any injection."""
    # fail-open: never block the agent
    with contextlib.suppress(Exception):
        emit_action(trigger, run_autopilot_event(trigger, payload))
