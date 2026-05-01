# SDK

## Purpose

Typed embedding surface for local, remote, and MCP-backed Atelier usage.

## Entry Points

- `__init__.py` — public SDK exports
- `client.py` — shared contracts and namespace clients
- `local.py` — in-process runtime adapter
- `remote.py` — HTTP service client wrapper
- `mcp.py` — MCP-compatible client wrapper

## Key Contracts

- `AtelierClient` is the stable factory surface.
- Namespace clients map to reasonblocks, rubrics, traces, failures, evals, and savings.
- SDK wraps existing runtime/service behavior; it should not invent new core semantics.
