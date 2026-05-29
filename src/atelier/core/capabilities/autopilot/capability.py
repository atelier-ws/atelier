"""Autopilot capability orchestrator (M5).

Pure and host-agnostic: it takes injected provider callables and returns an
:class:`AutopilotAction`. It performs the token-budget and dedup guards and is
fully fail-open. Telemetry/IO (emitting the action, recording to the ledger) is
the hook's job, keeping this layer testable.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Any

from atelier.core.capabilities.prompt_compilation.tokens import estimate_tokens

from .models import AutopilotAction, AutopilotConfig, AutopilotEvent
from .policy import select_behavior, should_inject_for_prompt

# Provider callable types (duck-typed return objects keep this decoupled).
RecallFn = Callable[[str], list[str]]
LessonsFn = Callable[[], list[str]]
ScopedPullFn = Callable[[str, list[str]], Any]  # (prompt, files) -> object with .chunks
VerifyFn = Callable[[list[str]], list[Any]]  # (files) -> objects with .to_prompt_block()


class AutopilotCapability:
    def __init__(
        self,
        config: AutopilotConfig,
        *,
        recall_fn: RecallFn | None = None,
        lessons_fn: LessonsFn | None = None,
        scoped_pull_fn: ScopedPullFn | None = None,
        verify_fn: VerifyFn | None = None,
    ) -> None:
        self.config = config
        self._recall_fn = recall_fn
        self._lessons_fn = lessons_fn
        self._scoped_pull_fn = scoped_pull_fn
        self._verify_fn = verify_fn
        self._seen: set[str] = set()

    def on_event(self, event: AutopilotEvent) -> AutopilotAction:
        if not self.config.enabled:
            return AutopilotAction.noop("disabled")
        try:
            behavior = select_behavior(event.trigger, self.config)
            if behavior is None:
                return AutopilotAction.noop("no_behavior")
            if behavior == "session_warm":
                return self._session_warm(event)
            if behavior == "scoped_inject":
                return self._scoped_inject(event)
            if behavior == "counterexamples":
                return self._counterexamples(event)
            return AutopilotAction.noop("no_behavior")
        except Exception:
            logging.exception("Recovered from broad exception handler")
            return AutopilotAction.noop("error")  # fail-open: never block the agent

    # -- behaviors ---------------------------------------------------------

    def _session_warm(self, event: AutopilotEvent) -> AutopilotAction:
        parts: list[str] = []
        if self._lessons_fn is not None:
            parts.extend(self._lessons_fn())
        if self._recall_fn is not None:
            query = str(event.payload.get("repo") or event.payload.get("cwd") or "")
            parts.extend(self._recall_fn(query))
        parts = [p for p in parts if p and p.strip()]
        if not parts:
            return AutopilotAction.noop("no_providers", "session_warm")
        content = "Relevant prior context (Atelier autopilot):\n" + "\n".join(f"- {p}" for p in parts)
        return self._emit("session_warm", content)

    def _scoped_inject(self, event: AutopilotEvent) -> AutopilotAction:
        if self._scoped_pull_fn is None:
            return AutopilotAction.noop("no_provider", "scoped_inject")
        prompt = str(event.payload.get("prompt") or "")
        if not prompt.strip():
            return AutopilotAction.noop("empty_prompt", "scoped_inject")
        if not should_inject_for_prompt(prompt):
            return AutopilotAction.noop("not_coding_prompt", "scoped_inject")
        files = list(event.payload.get("files") or [])
        scoped = self._scoped_pull_fn(prompt, files)
        chunks = list(getattr(scoped, "chunks", []) or [])
        if not chunks:
            return AutopilotAction.noop("no_chunks", "scoped_inject")
        # Keep it small + scoped: only the top-K most-relevant chunks (the pull
        # returns them ranked). Avoids the "lost in the middle" context dump.
        top = chunks[: self.config.max_inject_chunks]
        lines = [f"- {getattr(c, 'symbol', '') or getattr(c, 'path', '')} ({getattr(c, 'path', '')})" for c in top]
        content = "Scoped context for this request (Atelier autopilot):\n" + "\n".join(lines)
        return self._emit("scoped_inject", content)

    def _counterexamples(self, event: AutopilotEvent) -> AutopilotAction:
        if self._verify_fn is None:
            return AutopilotAction.noop("no_provider", "counterexamples")
        files = list(event.payload.get("touched_files") or [])
        if not files:
            return AutopilotAction.noop("no_files", "counterexamples")
        counterexamples = self._verify_fn(files)
        if not counterexamples:
            return AutopilotAction.noop("clean", "counterexamples")
        body = "\n".join(c.to_prompt_block() for c in counterexamples)
        content = "Verification found issues to fix before continuing (Atelier autopilot):\n" + body
        return self._emit("counterexamples", content)

    # -- guards ------------------------------------------------------------

    def _emit(self, behavior: str, content: str) -> AutopilotAction:
        content = content.strip()
        if not content:
            return AutopilotAction.noop("empty", behavior)
        budget = self.config.max_inject_tokens
        if estimate_tokens(content) > budget:
            content = self._truncate_to_budget(content, budget)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest in self._seen:
            return AutopilotAction.noop("deduped", behavior)
        self._seen.add(digest)
        return AutopilotAction(
            kind="inject",
            behavior=behavior,
            content=content,
            injected_tokens=estimate_tokens(content),
        )

    @staticmethod
    def _truncate_to_budget(content: str, budget_tokens: int) -> str:
        lines = content.splitlines()
        out: list[str] = []
        for line in lines:
            candidate = "\n".join([*out, line])
            if estimate_tokens(candidate) > budget_tokens:
                break
            out.append(line)
        result = "\n".join(out)
        return result if result else lines[0][: budget_tokens * 4]
