# Gateway Adapters

## Purpose

Host-facing integration surfaces for CLI, MCP, service, and embedded runtime adapters.

## Entry Points

- `cli.py` - primary `atelier` CLI surface
- `mcp_server.py` - MCP tool server and tool registry
- `runtime.py` - in-process runtime adapter used by product agents
- `http_api.py` - HTTP API adapter
- `remote_client.py` - service-mode remote client

## Key Contracts

- Adapters call one runtime orchestrator (`AtelierRuntimeCore`) for capability logic.
- Legacy command/tool surfaces remain available while new capability commands/tools are added.
- Host adapters are thin wrappers; policy and state logic live in core runtime/capabilities.
- Domain bundles are internal-only, loaded from built-in and local domain directories.

## Capability-driven tools and commands

- CLI: `capability list/status`, `memory summarize`, `read smart`, `edit smart`, `sql inspect`, `benchmark-runtime`, `benchmark-host`
- MCP (Core-6): `atelier_get_reasoning_context`, `atelier_check_plan`, `atelier_rescue_failure`, `atelier_record_trace`, `atelier_run_rubric_gate`, `atelier_compress_context`

## MCP Tool Surface (Core-6)

| Tool | Namespace | Purpose |
|---|---|---|
| `atelier_get_reasoning_context` | brain | Retrieves curated reasoning context from the ledger |
| `atelier_check_plan` | brain | Validates a plan against rubrics before execution |
| `atelier_rescue_failure` | brain | Suggests recovery for a failed step |
| `atelier_run_rubric_gate` | brain | Evaluates rubric checks, returns pass/warn/blocked/fail |
| `atelier_record_trace` | capture | Records trace + realtime prompt/response/bash compaction + optional Langfuse emit |
| `atelier_compress_context` | infra | Returns compact ledger prompt block plus realtime context snapshot |

Remote mode (`ATELIER_MCP_MODE=remote`) routes the first 5 tools through `remote_client.py`; `compress_context` is always local.

`atelier_rescue_failure` now enriches responses with failure-cluster analysis (`analysis`) derived from historical failed traces.

## OpenMemory CLI Notes

- `atelier openmemory status` always shows local bridge tools.
- `ATELIER_OPENMEMORY_ENABLED=true` switches mode to local + remote sync.
- Disabled remote mode still keeps local persistence available.

## Where to look next

- `src/atelier/core/runtime/engine.py`
- `src/atelier/core/capabilities/`
- `docs/core/runtime.md`
- `docs/core/capabilities.md`
