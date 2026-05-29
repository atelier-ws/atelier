"""Tests for the M5 autopilot choreography capability."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from atelier.core.capabilities.autopilot import AutopilotCapability, AutopilotConfig, AutopilotEvent
from atelier.core.capabilities.verification import Counterexample


def test_disabled_returns_noop() -> None:
    cap = AutopilotCapability(AutopilotConfig(enabled=False), lessons_fn=lambda: ["x"])
    action = cap.on_event(AutopilotEvent("session_start"))
    assert action.kind == "noop" and action.reason == "disabled"


def test_unknown_trigger_is_noop() -> None:
    cap = AutopilotCapability(AutopilotConfig())
    assert cap.on_event(AutopilotEvent("weird")).reason == "no_behavior"


def test_session_warm_injects_lessons() -> None:
    cap = AutopilotCapability(AutopilotConfig(), lessons_fn=lambda: ["prefer uv run", "hard-remove not deprecate"])
    action = cap.on_event(AutopilotEvent("session_start", {"cwd": "/repo"}))
    assert action.kind == "inject" and action.behavior == "session_warm"
    assert "prefer uv run" in action.content and action.injected_tokens > 0


def test_scoped_inject_uses_provider() -> None:
    seen: dict[str, Any] = {}

    def fake_pull(prompt: str, files: list[str]) -> Any:
        seen["prompt"] = prompt
        return SimpleNamespace(chunks=[SimpleNamespace(symbol="alpha", path="src/a.py")])

    cap = AutopilotCapability(AutopilotConfig(), scoped_pull_fn=fake_pull)
    action = cap.on_event(AutopilotEvent("user_prompt", {"prompt": "fix alpha"}))
    assert action.kind == "inject" and action.behavior == "scoped_inject"
    assert "alpha" in action.content and seen["prompt"] == "fix alpha"


def test_scoped_inject_noop_without_provider() -> None:
    cap = AutopilotCapability(AutopilotConfig())
    assert cap.on_event(AutopilotEvent("user_prompt", {"prompt": "x"})).reason == "no_provider"


def _inject_cap() -> AutopilotCapability:
    return AutopilotCapability(
        AutopilotConfig(),
        scoped_pull_fn=lambda prompt, files: SimpleNamespace(chunks=[SimpleNamespace(symbol="alpha", path="src/a.py")]),
    )


def test_gate_skips_meta_prompt() -> None:
    action = _inject_cap().on_event(AutopilotEvent("user_prompt", {"prompt": "what is prompt-gating?"}))
    assert action.kind == "noop" and action.reason == "not_coding_prompt"


def test_gate_skips_chat_prompt() -> None:
    for chat in ("yes", "thanks", "continue", "ok sounds good"):
        action = _inject_cap().on_event(AutopilotEvent("user_prompt", {"prompt": chat}))
        assert action.kind == "noop", f"{chat!r} should not inject"


def test_scoped_inject_caps_chunks() -> None:
    many = SimpleNamespace(chunks=[SimpleNamespace(symbol=f"s{i}", path=f"f{i}.py") for i in range(40)])
    cap = AutopilotCapability(AutopilotConfig(max_inject_chunks=8), scoped_pull_fn=lambda p, f: many)
    action = cap.on_event(AutopilotEvent("user_prompt", {"prompt": "refactor the parser module"}))
    assert action.kind == "inject"
    assert sum(1 for line in action.content.splitlines() if line.startswith("- ")) == 8


def test_gate_allows_coding_prompt() -> None:
    # coding verb
    a1 = _inject_cap().on_event(AutopilotEvent("user_prompt", {"prompt": "fix the failing auth flow"}))
    # code signal (filename / identifier)
    a2 = _inject_cap().on_event(AutopilotEvent("user_prompt", {"prompt": "what does tool_smart_read in a.py do"}))
    assert a1.kind == "inject" and a2.kind == "inject"


def test_counterexamples_injected() -> None:
    ce = Counterexample(check="typecheck", severity="error", file_path="a.py", line=1, diagnostic="bad")
    cap = AutopilotCapability(AutopilotConfig(), verify_fn=lambda files: [ce])
    action = cap.on_event(AutopilotEvent("post_edit", {"touched_files": ["a.py"]}))
    assert action.kind == "inject" and "<counterexample" in action.content


def test_counterexamples_clean_is_noop() -> None:
    cap = AutopilotCapability(AutopilotConfig(), verify_fn=lambda files: [])
    assert cap.on_event(AutopilotEvent("post_edit", {"touched_files": ["a.py"]})).reason == "clean"


def test_dedup_suppresses_repeat() -> None:
    cap = AutopilotCapability(AutopilotConfig(), lessons_fn=lambda: ["same"])
    first = cap.on_event(AutopilotEvent("session_start"))
    second = cap.on_event(AutopilotEvent("session_start"))
    assert first.kind == "inject" and second.reason == "deduped"


def test_budget_truncation() -> None:
    big = [f"lesson number {i} with some descriptive text" for i in range(500)]
    cap = AutopilotCapability(AutopilotConfig(max_inject_tokens=80), lessons_fn=lambda: big)
    action = cap.on_event(AutopilotEvent("session_start"))
    assert action.kind == "inject" and action.injected_tokens <= 80


def test_fail_open_on_provider_error() -> None:
    def boom() -> list[str]:
        raise RuntimeError("provider down")

    cap = AutopilotCapability(AutopilotConfig(), lessons_fn=boom)
    assert cap.on_event(AutopilotEvent("session_start")).reason == "error"
