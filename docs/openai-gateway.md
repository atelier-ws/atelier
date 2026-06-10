# Atelier OpenAI-Compatible Gateway

`atelier serve-openai` exposes Atelier's full execution loop as a standards-compliant `/v1/chat/completions` streaming endpoint. Any TUI that supports custom OpenAI-compatible providers can use Atelier as its brain — routing, caching, subagents, memory, and verification all stay inside Atelier.

## Start the gateway

```bash
atelier serve-openai --port 8787
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 8787 | TCP port |
| `--host` | 0.0.0.0 | Bind address |
| `--project-root` | cwd | Working directory for Atelier runtime |
| `--no-yolo` | off | Require manual approval for tool calls (default: auto-approve) |

## Connect a TUI

### OpenCode

`opencode.json` (project or `~/.config/opencode/opencode.json`):

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

### Crush

`crush.json`:

```json
{
  "$schema": "https://charm.land/crush.json",
  "providers": {
    "atelier": {
      "type": "openai-compat",
      "base_url": "http://localhost:8787/v1",
      "api_key": "local",
      "models": [
        {
          "id": "atelier-default",
          "name": "Atelier",
          "context_window": 200000,
          "default_max_tokens": 16000
        }
      ]
    }
  }
}
```

### Codex (`~/.codex/config.toml`)

```toml
model = "atelier-default"
model_provider = "atelier"

[model_providers.atelier]
name     = "Atelier"
base_url = "http://localhost:8787/v1"
env_key  = "ATELIER_API_KEY"
wire_api = "chat"
```

Set `ATELIER_API_KEY=local` (or any non-empty value) in your shell.

### Claude Code (MCP — zero configuration)

Atelier already ships `atelier-mcp`. Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "atelier": {
      "command": "atelier-mcp",
      "env": { "ATELIER_SERVICE_URL": "http://127.0.0.1:8787" }
    }
  }
}
```

### curl smoke test

```bash
curl -X POST http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer local" \
  -d '{"model":"atelier-default","messages":[{"role":"user","content":"hello"}],"stream":true}' \
  --no-buffer
```

Expected: SSE stream of `data: {...}` chunks, terminated by `data: [DONE]`.

## Architecture

```
TUI  ──POST /v1/chat/completions──►  openai_gateway/app.py
                                              │
                                        adapter.py
                                    (OpenAI ↔ NDJSON)
                                              │
                                  InteractiveRuntime.handle_user_message()
                                              │
                               Atelier routing / caching / subagents
```

Key properties:
- **Per-request session isolation** — each HTTP request gets a fresh session ID; prior messages are injected as history so context is preserved within a conversation.
- **Auto-approve in gateway mode** — `--no-yolo` disables this; without it the agent loop would block waiting for terminal input that never comes.
- **Streaming by default** — set `"stream": false` in the request body for a buffered response.
- **Tool calls visible** — tool calls Atelier makes during execution are forwarded as OpenAI function-call deltas so capable TUIs can display them.

## Available models

| Model ID | Description |
|----------|-------------|
| `atelier-default` | Atelier's auto-selected route (balanced) |
| `atelier-auto` | Same as default |
| `atelier-cheap` | Routes to cheapest available provider |
| `atelier-best` | Routes to highest-quality available provider |
