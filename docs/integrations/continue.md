# Continue.dev ← Atelier Integration

Continue.dev is an open-source AI assistant for VS Code and JetBrains.  Atelier
integrates as a **context provider** — injecting relevant reasoning blocks into
every chat prompt — and as an optional plan-validation step before inline edits
are applied.

## Architecture

```
Continue.dev IDE extension
        │
        │  HTTP  (context provider call)
        ▼
Atelier HTTP service  (:8123)
        │
        │  in-process
        ▼
LocalClient → ReasonBlock store → reasoning context
```

## Install

```bash
pip install atelier-runtime
atelier init
atelier serve          # starts the HTTP service on http://localhost:8123
```

## Configure Continue.dev

Add to `~/.continue/config.json`:

```json
{
  "contextProviders": [
    {
      "name": "http",
      "params": {
        "url": "http://localhost:8123/context",
        "title": "Atelier reasoning blocks",
        "description": "Relevant reasoning blocks for the current task"
      }
    }
  ]
}
```

The `/context` endpoint accepts a `query` parameter and returns text that
Continue prepends to the active prompt.

## Programmatic usage (Python)

```python
from atelier.gateway.adapters import ContinueAdapter, ContinueConfig
from atelier.sdk import AtelierClient

client = AtelierClient.local()
adapter = ContinueAdapter.from_config(
    ContinueConfig(mode="suggest", default_domain="Agent.codegen"),
    client=client,
)

# Retrieve context for a natural-language query
ctx = adapter.get_context(query="Add rate limiting to API gateway")
print(ctx.context)   # inject into system prompt

# Optionally validate a plan before applying inline edits
decision = adapter.check_plan(
    task="Add rate limiting",
    plan=["Modify api_gateway.py", "Add Redis rate-limit middleware"],
)
if decision.blocked:
    print("Blocked:", decision.warnings)
```

## Adapter modes

| Mode | Behaviour |
|------|-----------|
| `shadow` | Silently fetches context; never blocks. |
| `suggest` | Surfaces warnings in the Continue output panel. |
| `enforce` | Blocks inline-edit application if a dead-end is detected. |

## Configuration

```python
ContinueConfig(
    mode="suggest",
    default_domain="Agent.codegen",
    server_url="http://localhost:8123",   # override for remote Atelier service
    default_rubric_id=None,
    default_tools=[],
)
```

## Remote Atelier service

If Atelier runs as a shared service, update `server_url` and the Continue
config URL to point at the remote host.  Authentication is handled by the
HTTP service layer (see `docs/architecture/` for the API reference).

## See also

- [Host matrix](host-matrix.md)
