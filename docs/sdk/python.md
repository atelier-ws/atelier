# Atelier Python SDK

The Python SDK in `atelier.sdk` is the embeddable contract for service backends and custom hosts that want Atelier without shelling out.

The SDK now routes through one runtime orchestrator (`AtelierRuntimeCore`) that manages capability execution centrally.

## Install

```bash
cd atelier
uv sync --all-extras
```

## Client Types

- `AtelierClient.local(root=".atelier")` uses the in-process runtime and local store.
- `AtelierClient.remote(base_url=..., api_key=...)` targets the HTTP service.
- `AtelierClient.mcp(root=".atelier")` uses the MCP tool contract with a local loopback transport by default.

Concrete classes and namespaces shipped in Phase A/B:

- `AtelierClient`
- `LocalClient`
- `RemoteClient`
- `MCPClient`
- `ReasonBlockClient`
- `RubricClient`
- `TraceClient`
- `EvalClient`
- `SavingsClient`

## Core Workflow

```python
from atelier.sdk import AtelierClient

client = AtelierClient.local(root=".atelier")

context = client.get_reasoning_context(
    task="Fix Shopify JSON-LD availability",
    domain="Agent.pdp.schema",
)

check = client.check_plan(
    task="Publish Shopify product",
    domain="Agent.shopify.publish",
    plan=["Parse product handle from PDP URL"],
)

if check.status == "blocked":
    rescue = client.rescue_failure(
        task="Publish Shopify product",
        domain="Agent.shopify.publish",
        error="Known dead end triggered",
    )
    print(rescue.rescue)

gate = client.run_rubric_gate(
    rubric_id="rubric_shopify_publish",
    checks={"product_identity_uses_gid": True},
)

trace = client.traces.record(
    agent="sdk",
    domain="Agent.shopify.publish",
    task="Publish Shopify product",
    status="success",
)
```

## Namespaces

- `client.reasonblocks` / `client.blocks`: list, search, and fetch ReasonBlocks.
- `client.rubrics`: list, fetch, and run rubric gates.
- `client.traces`: record, list, and inspect traces.
- `client.failures`: analyze failure clusters.
- `client.evals`: run local eval fixtures or query remote eval status.
- `client.savings`: summarize cost and benchmark savings.

## Adapter Integration

For custom host middleware, the SDK can be extended via `src/atelier/adapters/`.
Each adapter supports `shadow`, `suggest`, and `enforce` modes.

## Capability-Aligned Operations

When using MCP-backed SDK clients, these tools map directly to core runtime capabilities:

- `atelier_reasoning_reuse`
- `atelier_semantic_memory`
- `atelier_loop_monitor`
- `atelier_tool_supervisor`
- `atelier_context_compressor`
- `atelier_smart_search`
- `atelier_smart_read`
- `atelier_smart_edit`
- `atelier_sql_inspect`
