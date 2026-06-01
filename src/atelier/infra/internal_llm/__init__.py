"""Internal local-model helpers for background-only processing.

Backend selection via ``ATELIER_LLM_BACKEND`` environment variable:

- ``none``              — disabled; all calls raise InternalLLMError (default)
- ``ollama``            — local Ollama server
- ``openai``            — OpenAI API or any OpenAI-compatible endpoint
- ``openai_compatible`` — alias for ``openai``

See ``openai_client.py`` for OpenRouter / opencode / local vllm configuration.
"""

from __future__ import annotations

import os
from typing import Any

from atelier.infra.internal_llm.exceptions import InternalLLMError, OllamaUnavailable


def _backend() -> str:
    return os.environ.get("ATELIER_LLM_BACKEND", "none").lower().strip()


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    json_schema: dict[str, Any] | None = None,
) -> str | dict[str, Any]:
    """Call the configured internal LLM chat endpoint."""
    backend = _backend()
    if backend == "none":
        raise InternalLLMError(
            "Internal LLM disabled; set ATELIER_LLM_BACKEND=ollama or ATELIER_LLM_BACKEND=openai to enable"
        )

    try:
        if backend in ("openai", "openai_compatible"):
            from atelier.infra.internal_llm.openai_client import chat as _chat

            return _chat(messages, model=model, json_schema=json_schema)

        from atelier.infra.internal_llm.ollama_client import chat as _chat

        return _chat(messages, model=model, json_schema=json_schema)
    except Exception as exc:
        if isinstance(exc, InternalLLMError):
            raise
        raise InternalLLMError(f"Internal LLM ({backend}) failed: {exc}") from exc


def summarize(text: str, *, model: str | None = None, max_tokens: int = 4096) -> str:
    """Summarize text using the configured internal LLM."""
    backend = _backend()
    if backend == "none":
        raise InternalLLMError(
            "Internal LLM disabled; set ATELIER_LLM_BACKEND=ollama or ATELIER_LLM_BACKEND=openai to enable"
        )

    try:
        if backend in ("openai", "openai_compatible"):
            from atelier.infra.internal_llm.openai_client import summarize as _summarize

            return _summarize(text, model=model, max_tokens=max_tokens)

        from atelier.infra.internal_llm.ollama_client import summarize as _summarize

        return _summarize(text, model=model, max_tokens=max_tokens)
    except Exception as exc:
        if isinstance(exc, InternalLLMError):
            raise
        raise InternalLLMError(f"Internal LLM ({backend}) failed: {exc}") from exc


__all__ = ["InternalLLMError", "OllamaUnavailable", "chat", "summarize"]
