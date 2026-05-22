"""Threshold-triggered tool-output compaction.

Head+tail compression strategy validated at -51.8% input tokens on SWE-bench Pro
(n=75 paired runs, Claude Sonnet 4.6) — ReasonBlocks TokenSavingMiddleware approach.

Key design choices:
- Char-based threshold (1800 chars) instead of token-based — predictable and fast
- Asymmetric head/tail split: head gets more budget (start has command, first error,
  context; tail has final result/status — middle is usually repetitive output)
- Ollama summarization is opt-in only; head+tail alone achieves the benchmark savings
"""

from __future__ import annotations

import json
import re
from typing import Literal

import tiktoken
from pydantic import BaseModel, ConfigDict

from atelier.infra.internal_llm.ollama_client import OllamaUnavailable, summarize

CompactMethod = Literal["passthrough", "deterministic_truncate", "ollama_summary"]
ContentType = Literal["file", "grep", "bash", "tool_output", "unknown"]

# Validated threshold from ReasonBlocks SWE-bench benchmark
DEFAULT_COMPRESS_THRESHOLD_CHARS = 1800
DEFAULT_HEAD_KEEP_CHARS = 900   # ~56% of budget — head has more signal
DEFAULT_TAIL_KEEP_CHARS = 700   # ~44% of budget — tail has final result/status


class CompactResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compacted: str
    original_tokens: int
    compacted_tokens: int
    recovery_hint: str
    method: CompactMethod
    content_type: str


_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def compress_tool_output(
    content: str,
    *,
    threshold_chars: int = DEFAULT_COMPRESS_THRESHOLD_CHARS,
    head_chars: int = DEFAULT_HEAD_KEEP_CHARS,
    tail_chars: int = DEFAULT_TAIL_KEEP_CHARS,
) -> str:
    """Head+tail compress a single tool output string.

    Returns the content unchanged when it is within the threshold.
    When above the threshold, returns head + omission notice + tail.

    This is a standalone helper matching the ReasonBlocks compress_tool_output()
    API, usable outside the compact MCP tool lifecycle.

    Args:
        content:         The tool output string.
        threshold_chars: Minimum length before compression is applied.
        head_chars:      Characters to keep from the start (default 900 — more
                         signal: command, first error, initial context).
        tail_chars:      Characters to keep from the end (default 700 — final
                         result, return value, last error).
    """
    if len(content) <= threshold_chars:
        return content
    elided = len(content) - head_chars - tail_chars
    return f"{content[:head_chars]}\n\n[... {elided} chars truncated ...]\n\n{content[-tail_chars:]}"


def _head_tail(text: str, *, max_chars: int) -> str:
    """Legacy helper — kept for backward compatibility with existing callers.

    Uses asymmetric split: 60% head / 40% tail.
    """
    if len(text) <= max_chars:
        return text
    head = max(1, int(max_chars * 0.6))
    tail = max(1, max_chars - head)
    elided = len(text) - head - tail
    return f"{text[:head]}\n... ({elided} chars elided) ...\n{text[-tail:]}"


def _compact_grep(content: str) -> str:
    grouped: dict[str, list[str]] = {}
    for line in content.splitlines():
        file_name = line.split(":", 1)[0] if ":" in line else "unknown"
        grouped.setdefault(file_name, []).append(line)
    parts: list[str] = []
    for file_name, lines in grouped.items():
        parts.extend(lines[:3])
        remaining = len(lines) - 3
        if remaining > 0:
            parts.append(f"... and {remaining} more in {file_name}")
    return "\n".join(parts)


def _compact_bash(content: str, budget_chars: int = 8000) -> str:
    """Compress bash output keeping head and tail by char budget."""
    stderr_match = re.search(r"stderr:\s*(.*)$", content, flags=re.IGNORECASE | re.DOTALL)
    stderr = stderr_match.group(1).strip() if stderr_match else ""
    if len(content) <= budget_chars:
        return content
    # Use asymmetric split: 60/40 head/tail
    head_chars = int(budget_chars * 0.6)
    tail_chars = budget_chars - head_chars
    compacted = compress_tool_output(content, threshold_chars=budget_chars, head_chars=head_chars, tail_chars=tail_chars)
    if stderr and "stderr" not in compacted:
        return f"{compacted}\n\nFull stderr:\n{stderr}"
    return compacted


def _compact_json(content: str) -> str | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        list_sample = data[:2]
        return json.dumps({"type": "list", "len": len(data), "sample": list_sample}, indent=2)
    if isinstance(data, dict):
        keys = sorted(data.keys())
        dict_sample = {key: data[key] for key in keys[:10]}
        return json.dumps({"type": "object", "keys": keys, "sample": dict_sample}, indent=2)
    return json.dumps({"type": type(data).__name__, "value": data}, indent=2)


def deterministic_truncate(content: str, content_type: str, budget_tokens: int) -> str:
    if content_type == "grep":
        return _compact_grep(content)
    if content_type == "bash":
        return _compact_bash(content, budget_chars=max(200, budget_tokens * 4))
    if content_type == "tool_output":
        compact_json = _compact_json(content)
        if compact_json is not None:
            return compact_json
    max_chars = max(200, budget_tokens * 4)
    return _head_tail(content, max_chars=max_chars)


def compact(
    content: str,
    content_type: str = "unknown",
    budget_tokens: int = 500,
    *,
    recovery_hint: str | None = None,
    enable_ollama: bool = False,
) -> CompactResult:
    """Compact tool output using char-based threshold + head/tail compression.

    Uses a char-based threshold (1800 chars by default) rather than token-based
    for consistency with the validated ReasonBlocks approach. Ollama summarization
    is opt-in only — head+tail alone achieves the benchmark -51.8% token savings.

    Args:
        content:       Tool output to compact.
        content_type:  One of file, grep, bash, tool_output, unknown.
        budget_tokens: Target token budget for the compacted result.
        recovery_hint: How to get the full output if needed.
        enable_ollama: If True, attempt LLM summarization for large outputs
                       when Ollama is available. Adds latency; off by default.
    """
    original_tokens = _count_tokens(content)
    hint = recovery_hint or "Re-run the original tool call or request the full output by path/range."

    # Passthrough: under the validated char threshold — no compression needed
    if len(content) <= DEFAULT_COMPRESS_THRESHOLD_CHARS:
        return CompactResult(
            compacted=content,
            original_tokens=original_tokens,
            compacted_tokens=original_tokens,
            recovery_hint=hint,
            method="passthrough",
            content_type=content_type,
        )

    method: CompactMethod = "deterministic_truncate"
    compacted = deterministic_truncate(content, content_type, budget_tokens)

    if enable_ollama and original_tokens > 2000 and content_type != "grep":
        try:
            prompt = f"Recovery hint: {hint}\n\nOutput to summarize:\n{content}"
            compacted = summarize(prompt, max_tokens=budget_tokens)
            method = "ollama_summary"
        except OllamaUnavailable:
            method = "deterministic_truncate"

    compacted_tokens = _count_tokens(compacted)
    return CompactResult(
        compacted=compacted,
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
        recovery_hint=hint,
        method=method,
        content_type=content_type,
    )


__all__ = ["CompactResult", "compact", "compress_tool_output", "deterministic_truncate"]
