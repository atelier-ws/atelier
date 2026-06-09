"""Event protocol between the Atelier runtime and the interactive CLI renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SessionStarted:
    type: Literal["session.started"]
    session_id: str
    project_root: str | None = None


@dataclass(frozen=True)
class AssistantDelta:
    type: Literal["assistant.delta"]
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    type: Literal["assistant.message"]
    text: str


@dataclass(frozen=True)
class RouteSelected:
    type: Literal["route.selected"]
    provider: str | None
    model: str | None
    reason: str | None = None


@dataclass(frozen=True)
class MemoryHit:
    type: Literal["memory.hit"]
    key: str
    summary: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class ToolRequested:
    type: Literal["tool.requested"]
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolStarted:
    type: Literal["tool.started"]
    id: str
    name: str


@dataclass(frozen=True)
class ToolOutput:
    type: Literal["tool.output"]
    id: str
    chunk: str
    stream: Literal["stdout", "stderr", "log"] = "log"


@dataclass(frozen=True)
class ToolFinished:
    type: Literal["tool.finished"]
    id: str
    name: str
    ok: bool
    result: Any | None = None


@dataclass(frozen=True)
class PatchProposed:
    type: Literal["patch.proposed"]
    id: str
    files: list[str]
    diff: str


@dataclass(frozen=True)
class PermissionRequested:
    type: Literal["permission.requested"]
    id: str
    action: str
    reason: str | None = None
    risk: Literal["low", "medium", "high"] = "medium"


@dataclass(frozen=True)
class VerificationResult:
    type: Literal["verification.result"]
    ok: bool
    rubric: str | None = None
    details: str | None = None


@dataclass(frozen=True)
class RuntimeErrorEvent:
    type: Literal["error"]
    message: str
    details: str | None = None


AtelierEvent = (
    SessionStarted
    | AssistantDelta
    | AssistantMessage
    | RouteSelected
    | MemoryHit
    | ToolRequested
    | ToolStarted
    | ToolOutput
    | ToolFinished
    | PatchProposed
    | PermissionRequested
    | VerificationResult
    | RuntimeErrorEvent
)


@dataclass(frozen=True)
class UserMessage:
    type: Literal["user.message"]
    text: str


@dataclass(frozen=True)
class UserSlashCommand:
    type: Literal["user.command"]
    name: str
    args: list[str]


@dataclass(frozen=True)
class PermissionResponse:
    type: Literal["permission.response"]
    id: str
    approved: bool
    scope: Literal["once", "session", "always"] = "once"


@dataclass(frozen=True)
class Interrupt:
    type: Literal["interrupt"]


AtelierInput = UserMessage | UserSlashCommand | PermissionResponse | Interrupt
