"""Internal local-model helpers for background-only processing."""

from atelier.infra.internal_llm.ollama_client import OllamaUnavailable, chat, summarize

__all__ = ["OllamaUnavailable", "chat", "summarize"]
