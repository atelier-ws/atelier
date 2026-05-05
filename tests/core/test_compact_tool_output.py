from __future__ import annotations

import pytest

from atelier.core.capabilities.tool_supervision.compact_output import compact
from atelier.infra.internal_llm.ollama_client import OllamaUnavailable


def test_compact_passthrough_under_threshold() -> None:
    result = compact("short output", content_type="tool_output")
    assert result.method == "passthrough"
    assert result.compacted == "short output"


def test_compact_groups_grep_output_deterministically() -> None:
    content = "\n".join(f"src/app.py:{i}: hit" for i in range(800))
    result = compact(content, content_type="grep", budget_tokens=80)
    assert result.method == "deterministic_truncate"
    assert "and 797 more" in result.compacted
    assert result.compacted_tokens < result.original_tokens


def test_compact_uses_ollama_for_large_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "atelier.core.capabilities.tool_supervision.compact_output.summarize",
        lambda prompt, max_tokens=500: "ollama compacted",
    )
    result = compact("alpha " * 2500, content_type="bash")
    assert result.method == "ollama_summary"
    assert result.compacted == "ollama compacted"


def test_compact_large_output_falls_back_when_ollama_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(prompt: str, max_tokens: int = 500) -> str:
        _ = (prompt, max_tokens)
        raise OllamaUnavailable("offline")

    monkeypatch.setattr(
        "atelier.core.capabilities.tool_supervision.compact_output.summarize",
        unavailable,
    )
    result = compact("alpha " * 2500, content_type="unknown", budget_tokens=100)
    assert result.method == "deterministic_truncate"
    assert result.compacted_tokens < result.original_tokens
