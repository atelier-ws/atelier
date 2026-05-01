"""Runtime monitors that watch agent execution and trigger rescue logic.

Six monitors are implemented:

1. RepeatedCommandFailure — same command/test fails twice with the same
   error signature.
2. RepeatedToolCall — same tool called 3+ times with similar args.
3. KnownDeadEnd — agent plan or tool args contain a known dead-end phrase.
4. SkippedVerification — agent attempts to mark success without verification.
5. ContextBloat — trace contains repeated logs / large stale tool output.
6. HighRiskAction — high-risk tool used without a matching rubric.

Each monitor implements `check(state) -> MonitorAlert | None`.
The monitors are deliberately stateless w.r.t. each other; the caller
maintains the running session state and feeds it to all monitors.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from atelier.core.foundation.models import ReasonBlock, Severity
from atelier.core.foundation.plan_checker import _step_matches_phrase  # internal reuse

# --------------------------------------------------------------------------- #
# Session state                                                               #
# --------------------------------------------------------------------------- #


@dataclass
class SessionState:
    """In-flight state used by monitors during a single agent run."""

    domain: str | None = None
    plan: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    command_results: list[tuple[str, bool, str]] = field(default_factory=list)
    """Tuples of (command, succeeded, error_signature)."""
    tool_calls: list[tuple[str, str]] = field(default_factory=list)
    """Tuples of (tool_name, args_signature)."""
    tool_outputs_chars: int = 0
    rubric_run: bool = False
    declared_success: bool = False
    validation_passed: bool = False
    file_events: list[tuple[str, str]] = field(default_factory=list)
    """Tuples of (path, action) where action in {'edit', 'revert'}."""
    estimated_tokens: int = 0
    budget_max_tool_calls: int | None = None
    budget_max_repeated_commands: int | None = None
    budget_max_estimated_tokens: int | None = None


@dataclass
class MonitorAlert:
    monitor: str
    severity: Severity
    message: str
    suggestion: str = ""


# --------------------------------------------------------------------------- #
# Protocol                                                                    #
# --------------------------------------------------------------------------- #


class Monitor(Protocol):
    name: str

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None: ...


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def error_signature(text: str) -> str:
    """Stable signature for an error string (volatile parts stripped)."""
    norm = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", text)
    norm = re.sub(r"\b\d+\b", "N", norm)
    norm = re.sub(r"\s+", " ", norm).strip().lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def args_signature(args: dict[str, Any] | str | None) -> str:
    if not args:
        return "()"
    if not isinstance(args, dict):
        return str(args)
    pairs = sorted((k, str(v)) for k, v in args.items())
    blob = "|".join(f"{k}={v}" for k, v in pairs)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Monitors                                                                    #
# --------------------------------------------------------------------------- #


class RepeatedCommandFailure:
    name = "repeated_command_failure"

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        sigs = [sig for _, ok, sig in state.command_results if not ok]
        counts = Counter(sigs)
        for sig, n in counts.items():
            if n >= 2:
                return MonitorAlert(
                    monitor=self.name,
                    severity="high",
                    message=f"Same command failed {n}x with error signature {sig}.",
                    suggestion=(
                        "Stop retrying. Search ReasonBlocks for this failure mode "
                        "and adjust the approach before re-running."
                    ),
                )
        return None


class RepeatedToolCall:
    name = "repeated_tool_call"

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        counts = Counter(state.tool_calls)
        for (tool, sig), n in counts.items():
            if n >= 3:
                return MonitorAlert(
                    monitor=self.name,
                    severity="medium",
                    message=f"Tool {tool!r} called {n}x with same args signature {sig}.",
                    suggestion=(
                        "Probable tight loop. Summarize the invariant the agent "
                        "is fighting and request a different procedure."
                    ),
                )
        return None


class KnownDeadEnd:
    name = "known_dead_end"

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        for block in blocks:
            for dead in block.dead_ends:
                for step in state.plan:
                    if _step_matches_phrase(step, dead):
                        return MonitorAlert(
                            monitor=self.name,
                            severity="high",
                            message=f"Plan contains known dead end: {dead!r}",
                            suggestion=(
                                f"Apply procedure from ReasonBlock '{block.title}' instead."
                            ),
                        )
        return None


class SkippedVerification:
    name = "skipped_verification"

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        if state.declared_success and not state.validation_passed:
            return MonitorAlert(
                monitor=self.name,
                severity="high",
                message="Agent declared success without verified validation.",
                suggestion=(
                    "Run the rubric gate before accepting the result. "
                    "No success without validation."
                ),
            )
        return None


class ContextBloat:
    name = "context_bloat"
    threshold_chars = 50_000

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        if state.tool_outputs_chars > self.threshold_chars:
            return MonitorAlert(
                monitor=self.name,
                severity="medium",
                message=(
                    f"Tool outputs accumulated {state.tool_outputs_chars} chars. "
                    "Likely stale repeated logs."
                ),
                suggestion=(
                    "Compress trace to: files changed, errors seen, assumptions "
                    "tested, current blocker."
                ),
            )
        return None


HIGH_RISK_TOOLS = {
    "shopify.update_metafield",
    "shopify.publish",
    "shopify.product.update",
    "schema.validate",
    "tracker.classify",
    "catalog.write",
    "pdp.publish",
}


class HighRiskAction:
    name = "high_risk_action"

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        for tool, _ in state.tool_calls:
            if tool in HIGH_RISK_TOOLS and not state.rubric_run:
                return MonitorAlert(
                    monitor=self.name,
                    severity="high",
                    message=f"High-risk tool {tool!r} used without a rubric gate.",
                    suggestion="Run the matching rubric gate before accepting this action.",
                )
        return None


class SecondGuessing:
    """Detect patch-revert-repatch cycles on the same file without new evidence."""

    name = "second_guessing"

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        per_file: dict[str, list[str]] = {}
        for path, action in state.file_events:
            per_file.setdefault(path, []).append(action)
        for path, actions in per_file.items():
            # edit -> revert -> edit on same file
            for i in range(len(actions) - 2):
                if actions[i] == "edit" and actions[i + 1] == "revert" and actions[i + 2] == "edit":
                    return MonitorAlert(
                        monitor=self.name,
                        severity="medium",
                        message=f"File {path!r} edited, reverted, edited again.",
                        suggestion=(
                            "Reset hypothesis. State the current assumption, the rejected "
                            "assumptions, and the next distinct strategy before editing again."
                        ),
                    )
        return None


class BudgetExhaustion:
    """Fire when configured budgets are exceeded."""

    name = "budget_exhaustion"

    def check(self, state: SessionState, blocks: Sequence[ReasonBlock]) -> MonitorAlert | None:
        if (
            state.budget_max_tool_calls is not None
            and len(state.tool_calls) > state.budget_max_tool_calls
        ):
            return MonitorAlert(
                monitor=self.name,
                severity="high",
                message=(
                    f"Tool call count {len(state.tool_calls)} exceeds budget "
                    f"{state.budget_max_tool_calls}."
                ),
                suggestion="Summarize-and-plan before continuing.",
            )
        if state.budget_max_repeated_commands is not None:
            counts = Counter(c for c, _, _ in state.command_results)
            for cmd, n in counts.items():
                if n > state.budget_max_repeated_commands:
                    return MonitorAlert(
                        monitor=self.name,
                        severity="high",
                        message=(
                            f"Command {cmd!r} repeated {n}x exceeds budget "
                            f"{state.budget_max_repeated_commands}."
                        ),
                        suggestion="Summarize-and-plan before continuing.",
                    )
        if (
            state.budget_max_estimated_tokens is not None
            and state.estimated_tokens > state.budget_max_estimated_tokens
        ):
            return MonitorAlert(
                monitor=self.name,
                severity="high",
                message=(
                    f"Estimated tokens {state.estimated_tokens} exceeds budget "
                    f"{state.budget_max_estimated_tokens}."
                ),
                suggestion="Summarize-and-plan before continuing.",
            )
        return None


def default_monitors() -> list[Monitor]:
    return [
        RepeatedCommandFailure(),
        RepeatedToolCall(),
        KnownDeadEnd(),
        SkippedVerification(),
        ContextBloat(),
        HighRiskAction(),
        SecondGuessing(),
        BudgetExhaustion(),
    ]


def run_monitors(
    state: SessionState,
    blocks: Sequence[ReasonBlock],
    monitors: Sequence[Monitor] | None = None,
) -> list[MonitorAlert]:
    monitors = monitors or default_monitors()
    alerts: list[MonitorAlert] = []
    for m in monitors:
        alert = m.check(state, blocks)
        if alert is not None:
            alerts.append(alert)
    return alerts
