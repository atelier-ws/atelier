"""Integration tests for the Atelier OpenAI-compatible gateway.

These tests verify the HTTP surface (schemas, routing, streaming format) using
FastAPI's TestClient. They do NOT start a real Atelier runtime — the runtime is
mocked so tests run offline and quickly.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Minimal AtelierEvent stubs — avoids importing the full runtime
# ---------------------------------------------------------------------------

class _Delta:
    type = "assistant.delta"
    def __init__(self, text: str) -> None:
        self.text = text

class _Message:
    type = "assistant.message"
    def __init__(self, text: str) -> None:
        self.text = text

class _Error:
    type = "error"
    def __init__(self, message: str) -> None:
        self.message = message


async def _stream(*events) -> AsyncIterator:
    for ev in events:
        yield ev


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_runtime():
    """Return a mock InteractiveRuntime that does NOT call the real LLM."""
    rt = MagicMock()
    rt.start_session = AsyncMock(return_value="test-session-id")
    rt.shutdown = MagicMock()
    rt._sessions = {}
    return rt


@pytest.fixture()
def client(mock_runtime):
    """Return a TestClient wired to a mock runtime."""
    with patch(
        "atelier.gateway.openai_gateway.app.InteractiveRuntime",
        return_value=mock_runtime,
    ):
        from atelier.gateway.openai_gateway.app import create_app
        app = create_app(project_root=None, yolo=True)
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c, mock_runtime


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health(client):
    c, _ = client
    resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_models(client):
    c, _ = client
    resp = c.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    model_ids = [m["id"] for m in data["data"]]
    assert "atelier-default" in model_ids
    assert "atelier-auto" in model_ids


def test_chat_nonstreaming(client):
    c, rt = client
    rt.handle_user_message = MagicMock(
        return_value=_stream(_Delta("Hello"), _Message("Hello world"))
    )

    resp = c.post(
        "/v1/chat/completions",
        json={
            "model": "atelier-default",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    content = body["choices"][0]["message"]["content"]
    assert "Hello" in content


def test_chat_streaming(client):
    c, rt = client
    rt.handle_user_message = MagicMock(
        return_value=_stream(_Delta("tok1"), _Delta("tok2"), _Message("tok1tok2"))
    )

    resp = c.post(
        "/v1/chat/completions",
        json={
            "model": "atelier-default",
            "messages": [{"role": "user", "content": "stream test"}],
            "stream": True,
        },
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    raw = resp.text
    assert "data: " in raw
    assert "[DONE]" in raw

    # Every data line (except [DONE]) must be valid JSON with choices
    for line in raw.splitlines():
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            obj = json.loads(line[6:])
            assert "choices" in obj, f"Missing choices in chunk: {line}"


def test_empty_messages(client):
    c, _ = client
    resp = c.post(
        "/v1/chat/completions",
        json={"model": "atelier-default", "messages": []},
    )
    assert resp.status_code == 422


def test_no_user_message(client):
    c, _ = client
    resp = c.post(
        "/v1/chat/completions",
        json={
            "model": "atelier-default",
            "messages": [{"role": "system", "content": "You are helpful."}],
        },
    )
    assert resp.status_code == 422


def test_error_event_in_stream(client):
    c, rt = client
    rt.handle_user_message = MagicMock(
        return_value=_stream(_Error("something went wrong"))
    )

    resp = c.post(
        "/v1/chat/completions",
        json={
            "model": "atelier-default",
            "messages": [{"role": "user", "content": "trigger error"}],
            "stream": True,
        },
    )
    assert resp.status_code == 200
    raw = resp.text
    assert "error" in raw.lower()
    assert "[DONE]" in raw
