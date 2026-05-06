"""Thin Ollama wrapper for Atelier's internal background processing."""

from __future__ import annotations

import json
from typing import Any


class OllamaUnavailable(RuntimeError):
    """Raised when the optional Ollama dependency or server is unavailable."""


def _ollama_module() -> Any:
    try:
        import ollama
    except ImportError as exc:  # pragma: no cover - exercised by tests via monkeypatch
        raise OllamaUnavailable("ollama package is not installed; install atelier[smart]") from exc
    return ollama


def summarize(text: str, *, model: str = "qwen3.6:latest", max_tokens: int = 4096) -> str:
    """Summarize text with a local Ollama model."""
    prompt = (
        "Summarize the following material for later engineering recall. Keep concrete file, "
        "command, error, and verification details.\n\n"
        f"Maximum output tokens: {max_tokens}\n\n{text}"
    )
    try:
        response = _ollama_module().generate(
            model=model,
            prompt=prompt,
            options={"num_predict": max_tokens},
        )
    except Exception as exc:  # pragma: no cover - depends on local server
        raise OllamaUnavailable(f"Ollama server unavailable: {exc}") from exc
    if isinstance(response, dict):
        return str(response.get("response", ""))
    return str(getattr(response, "response", ""))


def chat(
    messages: list[dict[str, str]],
    *,
    model: str = "qwen3.6:latest",
    json_schema: dict[str, Any] | None = None,
) -> str | dict[str, Any]:
    """Call Ollama chat and optionally parse a JSON response."""
    options: dict[str, Any] = {}
    try:
        if json_schema is None:
            response = _ollama_module().chat(model=model, messages=messages, options=options)
        else:
            response = _ollama_module().chat(
                model=model,
                messages=messages,
                format="json",
                options=options,
            )
    except TypeError as exc:
        if json_schema is None:
            raise OllamaUnavailable(f"Ollama server unavailable: {exc}") from exc
        try:
            legacy_options = {**options, "format": "json"}
            response = _ollama_module().chat(model=model, messages=messages, options=legacy_options)
        except Exception as exc:  # pragma: no cover - depends on local server
            raise OllamaUnavailable(f"Ollama server unavailable: {exc}") from exc
    except Exception as exc:  # pragma: no cover - depends on local server
        raise OllamaUnavailable(f"Ollama server unavailable: {exc}") from exc
    message = response.get("message", {}) if isinstance(response, dict) else getattr(response, "message", {})
    content = message.get("content", "") if isinstance(message, dict) else getattr(message, "content", "")
    if json_schema is None:
        return str(content)
    try:
        parsed = json.loads(str(content))
    except json.JSONDecodeError as exc:
        raise OllamaUnavailable(f"Ollama returned invalid JSON: {exc}") from exc
    return parsed if isinstance(parsed, dict) else {"value": parsed}


__all__ = ["OllamaUnavailable", "chat", "summarize"]
