# tool_supervision

## Purpose

Supervises tool-call behavior: caching, retry prevention, anomaly/circuit monitoring, and observability metrics.

## Entry Point

`__init__.py` re-exports `ToolSupervisionCapability`.

## Module Layout

| File                 | Responsibility                                                       |
| -------------------- | -------------------------------------------------------------------- |
| `capability.py`      | Main API: `observe/get/status/tool_report/diff_context/test_context` |
| `circuit_breaker.py` | Native circuit breaker state machine                                 |
| `anomaly.py`         | Rolling-window anomaly and burst detection                           |
| `store.py`           | Disk-backed cache + history                                          |
| `models.py`          | Circuit/anomaly model types                                          |

## Key Contracts

- Constructor: `ToolSupervisionCapability(root: Path)`
- `status()` returns core metrics plus per-tool call histogram
- `retries_prevented` tracks blocked retries from open-circuit behavior
- `test_context(paths)` returns `{"test_contexts": [{"path", "exists", "test_files"}]}`

## Integrations

- `tenacity` (optional): retries transient store read/write operations
- `prometheus_client` (optional): emits counters and latency histograms
- `pybreaker` (optional): secondary circuit model for additional guardrails

## Where to look next

- `src/atelier/core/runtime/engine.py`
