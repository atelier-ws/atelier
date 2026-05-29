"""Data models for autopilot choreography (M5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AutopilotConfig:
    """Master + per-behavior toggles.

    Default is on for the safe session-warm behavior. The scoped-inject and
    counterexample behaviors are also on by default but are guarded (scoped
    pull, token budget, dedup, fail-open) and degrade to noop when their
    provider is unavailable.
    """

    enabled: bool = True
    session_warm: bool = True
    scoped_inject: bool = True
    counterexamples: bool = True
    max_inject_tokens: int = 1500
    # Keep injected context small + scoped (Augment-style: avoid "lost in the
    # middle" from dumping an undifferentiated slice). Inject only the top-K
    # most-relevant chunks the scoped pull returned.
    max_inject_chunks: int = 8


@dataclass
class AutopilotEvent:
    """A host lifecycle event the autopilot may react to."""

    trigger: str  # "session_start" | "user_prompt" | "post_edit"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutopilotAction:
    """The autopilot's decision for an event."""

    kind: str  # "inject" | "noop"
    behavior: str = ""
    content: str = ""
    reason: str = ""
    injected_tokens: int = 0

    @classmethod
    def noop(cls, reason: str, behavior: str = "") -> AutopilotAction:
        return cls(kind="noop", behavior=behavior, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "behavior": self.behavior,
            "content": self.content,
            "reason": self.reason,
            "injected_tokens": self.injected_tokens,
        }
