"""Threshold-triggered tool-output compaction."""

from __future__ import annotations

import json
import re
from typing import Literal

import tiktoken
from pydantic import BaseModel, ConfigDict

from atelier.infra.internal_llm.ollama_client import OllamaUnavailable, summarize

CompactMethod = Literal["passthrough", "deterministic_truncate", "ollama_summary"]
ContentType = Literal["file", "grep", "bash", "tool_output", "unknown"]


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


def _head_tail(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max(1, max_chars // 2)
    return f"{text[:half]}\n... ({len(text) - max_chars} chars elided) ...\n{text[-half:]}"


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


def _compact_bash(content: str) -> str:
    stderr_match = re.search(r"stderr:\s*(.*)$", content, flags=re.IGNORECASE | re.DOTALL)
    stderr = stderr_match.group(1).strip() if stderr_match else ""
    lines = content.splitlines()
    if len(lines) <= 120:
        return content
    compacted = "\n".join([*lines[:50], f"... ({len(lines) - 100} lines elided) ...", *lines[-50:]])
    if stderr:
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
        return _compact_bash(content)
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
) -> CompactResult:
    """Compact tool output based on token thresholds."""
    original_tokens = _count_tokens(content)
    hint = recovery_hint or "Re-run the original tool call or request the full output by path/range."
    if original_tokens < 500:
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
    if original_tokens > 2000 and content_type != "grep":
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


__all__ = ["CompactResult", "compact", "deterministic_truncate"]
