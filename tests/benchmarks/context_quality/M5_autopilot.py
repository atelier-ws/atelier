"""M5 — Autopilot choreography benchmark: bounded-overhead + correctness.

The quality half (does auto-injected context improve task success?) requires a
live model and is deferred. This benchmark measures the deterministic guards
that make on-by-default safe:

* every injection respects the token budget (no context-spam blowups),
* repeated identical context is deduplicated (not re-injected),
* each host trigger maps to the correct behavior, and the master switch off
  yields a noop.

Run explicitly (slow):
    uv run pytest tests/benchmarks/context_quality/M5_autopilot.py -v -m slow
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from atelier.core.capabilities.autopilot import AutopilotCapability, AutopilotConfig, AutopilotEvent
from atelier.core.capabilities.verification import Counterexample

_BUDGET = 1500


def _chunks(n: int) -> Any:
    return SimpleNamespace(chunks=[SimpleNamespace(symbol=f"sym_{i}", path=f"src/m_{i}.py") for i in range(n)])


def _capability() -> AutopilotCapability:
    return AutopilotCapability(
        AutopilotConfig(max_inject_tokens=_BUDGET),
        lessons_fn=lambda: ["prefer uv run", "hard-remove not deprecate"],
        scoped_pull_fn=lambda prompt, files: _chunks(60),  # oversized on purpose
        verify_fn=lambda files: [
            Counterexample(check="lint", severity="error", file_path="a.py", line=i, diagnostic="x" * 50)
            for i in range(40)
        ],
    )


@pytest.mark.slow
def test_m5_overhead_and_correctness() -> None:
    cap = _capability()

    # 1. Budget: oversized injections are clamped under the token budget.
    prompt_action = cap.on_event(AutopilotEvent("user_prompt", {"prompt": "implement the parser"}))
    post_action = cap.on_event(AutopilotEvent("post_edit", {"touched_files": ["a.py"]}))
    warm_action = cap.on_event(AutopilotEvent("session_start", {"cwd": "/repo"}))

    injections = [a for a in (prompt_action, post_action, warm_action) if a.kind == "inject"]
    assert injections, "expected at least one injection"
    max_tokens = max(a.injected_tokens for a in injections)
    assert max_tokens <= _BUDGET, f"injection {max_tokens} exceeded budget {_BUDGET}"

    # 2. Correctness: triggers map to the right behaviors.
    assert prompt_action.behavior == "scoped_inject"
    assert post_action.behavior == "counterexamples"
    assert warm_action.behavior == "session_warm"

    # 3. Dedup: a repeated prompt is not re-injected.
    repeat = cap.on_event(AutopilotEvent("user_prompt", {"prompt": "implement the parser"}))
    assert repeat.kind == "noop" and repeat.reason == "deduped"

    # 4. Master switch off -> noop.
    off = AutopilotCapability(AutopilotConfig(enabled=False), lessons_fn=lambda: ["x"])
    assert off.on_event(AutopilotEvent("session_start")).kind == "noop"
