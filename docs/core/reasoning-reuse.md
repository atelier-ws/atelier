# Reasoning Reuse

Capability path:
- `src/atelier/core/capabilities/reasoning_reuse/`

## Purpose

Reasoning reuse surfaces successful prior procedures and failure-aligned guidance.

## Behavior

- ranks procedures by task, domain, files, tools, and error context
- merges learned runtime procedures with internal domain procedures
- returns high-signal procedures for runtime injection

## Runtime API

- `AtelierRuntimeCore.get_reasoning_context(...)`
- MCP: `atelier_reasoning_reuse`
