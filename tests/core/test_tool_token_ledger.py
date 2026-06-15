"""N4 — per-tool exact input/output token ledger."""

from __future__ import annotations

from pathlib import Path

from atelier.core.capabilities.prompt_compilation.tokens import estimate_tokens
from atelier.core.capabilities.tool_token_ledger import (
    TOOL_TOKEN_LEDGER_FILENAME,
    ToolTokenLedger,
    count_payload_tokens,
    load_tool_token_ledger,
    record_tool_tokens,
)


def test_count_payload_tokens_matches_local_counter_for_strings() -> None:
    text = "def calculate_total(items: list[int]) -> int:\n    return sum(items)\n"
    assert count_payload_tokens(text) == estimate_tokens(text)
    assert count_payload_tokens("") == 0
    assert count_payload_tokens(None) == 0


def test_count_payload_tokens_serialises_non_strings() -> None:
    payload = {"path": "src/a.py", "line": 12}
    # Non-string payloads are JSON-rendered before counting; result is > 0.
    assert count_payload_tokens(payload) > 0


def test_record_tool_tokens_accumulates_per_tool(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    record_tool_tokens(root, "read", input_payload={"path": "a.py"}, output_payload="hello world")
    record_tool_tokens(root, "read", input_payload={"path": "b.py"}, output_payload="second body here")
    record_tool_tokens(root, "grep", input_payload={"content_regex": "foo"}, output_payload="match line")

    ledger = load_tool_token_ledger(root)
    assert ledger.per_tool["read"].calls == 2
    assert ledger.per_tool["grep"].calls == 1
    # Input/output token counts are accumulated and strictly positive.
    assert ledger.per_tool["read"].input_tokens > 0
    assert ledger.per_tool["read"].output_tokens > 0
    assert ledger.total_calls() == 3
    assert ledger.total_input_tokens() == (ledger.per_tool["read"].input_tokens + ledger.per_tool["grep"].input_tokens)


def test_record_tool_tokens_exact_output_count(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    body = "the quick brown fox jumps over the lazy dog " * 10
    record_tool_tokens(root, "search", input_payload={"query": "x"}, output_payload=body)
    ledger = load_tool_token_ledger(root)
    # The output token count is exactly what the local counter reports for the
    # emitted text — no estimation, no network call.
    assert ledger.per_tool["search"].output_tokens == estimate_tokens(body)


def test_ledger_persists_to_named_sidecar(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    record_tool_tokens(root, "read", input_payload={"path": "a.py"}, output_payload="body")
    sidecar = root / TOOL_TOKEN_LEDGER_FILENAME
    assert sidecar.exists()
    # Reload from disk reconstructs the same totals.
    reloaded = load_tool_token_ledger(root)
    assert reloaded.total_calls() == 1


def test_load_empty_when_absent(tmp_path: Path) -> None:
    ledger = load_tool_token_ledger(tmp_path / "missing")
    assert isinstance(ledger, ToolTokenLedger)
    assert ledger.total_calls() == 0
    assert ledger.to_dict()["totals"]["calls"] == 0


def test_load_tolerates_corrupt_sidecar(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir(parents=True)
    (root / TOOL_TOKEN_LEDGER_FILENAME).write_text("{not json", encoding="utf-8")
    ledger = load_tool_token_ledger(root)
    assert ledger.total_calls() == 0


def test_empty_tool_name_is_ignored(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    record_tool_tokens(root, "", input_payload={"a": 1}, output_payload="x")
    assert load_tool_token_ledger(root).total_calls() == 0
