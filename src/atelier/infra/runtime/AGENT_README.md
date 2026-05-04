# Runtime

## Purpose

Core runtime helpers for reasoning sessions, telemetry, and benchmarking.

## Entry Points

- `benchmarking.py` — reusable benchmark workflows and report IO
- `cost_tracker.py` — cost and savings accounting
- `context_compressor.py` — compact state projection from run ledger
- `realtime_context.py` — rolling, persistent context minimization for next-call prompts

## Key Contracts

- benchmark helpers must keep report JSON stable enough for CLI compare/report/export
- runtime helpers should stay host-neutral and reusable from CLI, SDK, and service layers
- realtime context manager must fail-open and keep the latest context snapshot under `<ATELIER_ROOT>/runtime/realtime_context.json`
