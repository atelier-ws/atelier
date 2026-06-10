# Phase 14 Plan: OpenAI-Compatible Gateway

**Phase goal**: `atelier serve-openai` — expose Atelier's execution loop as a streaming `/v1/chat/completions` endpoint so any standard TUI (OpenCode, Crush, Codex, Claude Code) connects without code changes; Atelier owns routing, caching, subagents, memory.

**Verification benchmark**: OpenCode pointed at `http://localhost:8787` sends a message, receives a streaming response, and the Atelier runtime log shows route selection + agent loop execution.

---

## Architecture

```
TUI  ──POST /v1/chat/completions──►  openai_gateway/app.py  ──►  InteractiveRuntime
                                              │                        │
                                        adapter.py              handle_user_message()
                                    (OpenAI ↔ NDJSON)           yields AtelierEvents
                                              │                        │
                                       SSE stream ◄──────────── AssistantDelta/Message
```

**Key insight**: `InteractiveRuntime.handle_user_message()` is already an async generator that yields `AtelierEvent` objects. The gateway is a thin SSE wrapper around it.

---

## Tasks

### Wave 1 — Module scaffold

**T1** Create gateway module `src/atelier/gateway/openai_gateway/__init__.py`
- Empty module init
- **Verify**: `python -c "from atelier.gateway.openai_gateway import app"` imports cleanly

**T2** Create `src/atelier/gateway/openai_gateway/schemas.py`
- Pydantic models matching OpenAI wire format (no external openai dep needed):
  ```python
  class ChatMessage(BaseModel):
      role: str           # "user" | "assistant" | "system" | "tool"
      content: str | list | None = None
      tool_call_id: str | None = None
      name: str | None = None

  class ChatCompletionRequest(BaseModel):
      model: str
      messages: list[ChatMessage]
      stream: bool = True
      temperature: float | None = None
      max_tokens: int | None = None
      tools: list[dict] | None = None          # pass-through if TUI sends tools
      tool_choice: str | dict | None = None

  class DeltaChoice(BaseModel):
      index: int = 0
      delta: dict                              # {"content": "..."} or {"tool_calls": [...]}
      finish_reason: str | None = None

  class ChatCompletionChunk(BaseModel):
      id: str
      object: str = "chat.completion.chunk"
      created: int
      model: str
      choices: list[DeltaChoice]
  ```
- **Verify**: models import, `ChatCompletionRequest(model="x", messages=[])` parses

### Wave 2 — Adapter

**T3** Create `src/atelier/gateway/openai_gateway/adapter.py`

Key function: `async def atelier_events_to_sse(events: AsyncIterator[AtelierEvent], model: str, chunk_id: str) -> AsyncIterator[str]`

Conversion rules:
- `AssistantDelta(text=t)` → `data: {"id":..., "choices":[{"delta":{"content":t}}]}\n\n`
- `AssistantMessage(text=t)` → final delta with `"finish_reason":"stop"` then `data: [DONE]\n\n`
- `ToolRequested(id, name, args)` → `data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":id,"type":"function","function":{"name":name,"arguments":json.dumps(args)}}]}}]}\n\n`
- `ToolOutput(id, chunk)` → no SSE (internal, skip)
- `ToolFinished` → no SSE (internal, skip)
- `CacheStats`, `ContextUsageUpdated` → no SSE (skip)
- `RuntimeErrorEvent(message=m)` → `data: {"error":{"message":m}}\n\n` then stop
- All others → skip (don't forward session.started, route.selected etc. to client)

Second function: `def openai_messages_to_atelier(messages: list[ChatMessage]) -> tuple[str, list[dict]]`
- Extract the last user message as the text to send: `last_user = [m for m in messages if m.role == "user"][-1]`
- Extract prior messages (for session context) as a list of `{"role": ..., "content": ...}` dicts
- Returns `(last_user_text, prior_history)`

**Verify**: Unit test — feed a list of `AtelierEvent` mocks through `atelier_events_to_sse`, assert SSE output matches expected strings.

### Wave 3 — FastAPI app

**T4** Create `src/atelier/gateway/openai_gateway/app.py`

```python
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from atelier.gateway.cli.runtime import InteractiveRuntime
from .schemas import ChatCompletionRequest
from .adapter import atelier_events_to_sse, openai_messages_to_atelier
import uuid, time

def create_app(project_root: str | None = None) -> FastAPI:
    app = FastAPI(title="Atelier OpenAI Gateway")
    runtime = InteractiveRuntime(root=project_root)

    @app.on_event("startup")
    async def _startup():
        await runtime.start_session()  # warm up

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest):
        session_id = str(uuid.uuid4())
        last_text, prior = openai_messages_to_atelier(req.messages)

        # Restore prior conversation context into the session
        runtime._sessions[session_id] = prior

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        events = runtime.handle_user_message(session_id, last_text)
        sse = atelier_events_to_sse(events, req.model, chunk_id)

        if req.stream:
            return StreamingResponse(sse, media_type="text/event-stream")
        else:
            # Accumulate and return non-streaming response
            content = ""
            async for chunk in sse:
                if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                    try:
                        obj = json.loads(chunk[6:])
                        delta = obj["choices"][0]["delta"]
                        content += delta.get("content", "")
                    except Exception:
                        pass
            return {"id": chunk_id, "object": "chat.completion", "created": int(time.time()),
                    "model": req.model, "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}

    @app.get("/v1/models")
    async def list_models():
        return {"object": "list", "data": [
            {"id": "atelier-default", "object": "model", "created": 0, "owned_by": "atelier"},
            {"id": "atelier-auto", "object": "model", "created": 0, "owned_by": "atelier"},
        ]}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
```

**Verify**: `create_app()` returns a FastAPI instance without errors

### Wave 4 — CLI integration

**T5** Create `src/atelier/gateway/openai_gateway/serve.py`

```python
"""Entry point for `atelier serve-openai`."""
import uvicorn
from .app import create_app

def serve(port: int = 8787, project_root: str | None = None, host: str = "0.0.0.0") -> None:
    app = create_app(project_root=project_root)
    uvicorn.run(app, host=host, port=port, log_level="info")
```

**T6** Add `serve-openai` Click command to `src/atelier/gateway/cli/commands/__init__.py`

```python
@_click.command("serve-openai")
@_click.option("--port", default=8787, help="Port to listen on")
@_click.option("--host", default="0.0.0.0", help="Bind address")
@_click.option("--project-root", default=None, help="Project root directory")
def serve_openai_cmd(port: int, host: str, project_root: str | None) -> None:
    """Start the OpenAI-compatible chat completions gateway.

    Any TUI that supports custom OpenAI-compatible endpoints can connect:

    \b
    OpenCode:  opencode.json → provider.atelier.options.baseURL = http://localhost:8787/v1
    Crush:     crush.json → providers.atelier.base_url = http://localhost:8787/v1/
    Codex:     ~/.codex/config.toml → model_providers.atelier.base_url = http://localhost:8787/v1
    """
    from atelier.gateway.openai_gateway.serve import serve
    serve(port=port, host=host, project_root=project_root)

cli.add_command(serve_openai_cmd, name="serve-openai")
```

**Verify**: `atelier serve-openai --help` shows the command with options

### Wave 5 — Dependencies and docs

**T7** Verify `fastapi` and `uvicorn` are in `pyproject.toml` dependencies
- Check `pyproject.toml` — both are likely already there (service/api.py uses them)
- If not present, add: `"fastapi>=0.111", "uvicorn[standard]>=0.30"`

**T8** Create `docs/openai-gateway.md` — quick integration guide for OpenCode/Crush/Codex
- Show the 3-line config for each TUI
- Start command: `atelier serve-openai --port 8787`
- Note: stream=true required for best experience

### Wave 6 — Integration test

**T9** Create `tests/gateway/test_openai_gateway.py`

Tests:
1. `test_health()` — GET /health returns 200
2. `test_models()` — GET /v1/models returns model list
3. `test_chat_nonstreaming()` — POST /v1/chat/completions stream=false returns a message
4. `test_chat_streaming()` — POST /v1/chat/completions stream=true returns SSE
5. `test_empty_input()` — empty messages returns 422
6. `test_concurrent_sessions()` — two concurrent requests get separate responses

**Verify**: `uv run pytest tests/gateway/test_openai_gateway.py -q`

---

## Dependency Map

```
T1 (module scaffold)
  └── T2 (schemas)
        └── T3 (adapter)
              └── T4 (FastAPI app)
                    ├── T5 (serve.py)
                    │     └── T6 (CLI command)
                    └── T7 (deps check)

T8 (docs) — independent
T9 (tests) — depends on T4
```

Waves 1-2 can run in parallel internally. T6 depends on T5.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `InteractiveRuntime` has per-instance state; concurrent requests share a runtime | Create one runtime per request OR use a session pool keyed by client IP/session header |
| Permission prompts (`permission.requested`) block the agent loop indefinitely | Auto-approve in gateway mode by default (add `--yolo` to runtime init) OR skip and return what was done |
| `AssistantMessage` vs streaming delta ordering | Yield `finish_reason: stop` only on `AssistantMessage`, not on `AssistantDelta` |
| OpenCode expects specific `model` field in responses | Echo back the `model` from the request in all response chunks |
| uvicorn not in pyproject.toml | Check and add if needed before T5 |

---

## Config Snippets (from research)

**OpenCode** (`opencode.json`):
```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "atelier": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Atelier",
      "options": {
        "baseURL": "http://localhost:8787/v1",
        "apiKey": "local"
      },
      "models": {
        "atelier-default": { "name": "Atelier Default" }
      }
    }
  },
  "model": "atelier/atelier-default"
}
```

**Crush** (`crush.json`):
```json
{
  "$schema": "https://charm.land/crush.json",
  "providers": {
    "atelier": {
      "type": "openai-compat",
      "base_url": "http://localhost:8787/v1",
      "api_key": "local",
      "models": [{ "id": "atelier-default", "name": "Atelier", "context_window": 200000, "default_max_tokens": 16000 }]
    }
  }
}
```

**Codex** (`~/.codex/config.toml`):
```toml
model = "atelier-default"
model_provider = "atelier"
[model_providers.atelier]
name = "Atelier"
base_url = "http://localhost:8787/v1"
env_key = "ATELIER_API_KEY"
wire_api = "chat"
```

---

## Completion Criteria

- [ ] `atelier serve-openai --port 8787` starts without error
- [ ] `curl -X POST http://localhost:8787/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"atelier-default","messages":[{"role":"user","content":"hello"}],"stream":true}' --no-buffer` streams SSE tokens
- [ ] `curl http://localhost:8787/v1/models` returns model list JSON
- [ ] All 6 unit tests pass: `uv run pytest tests/gateway/test_openai_gateway.py -q`
- [ ] OpenCode with the config above connects and sends/receives a message end-to-end
