# Runtime

## Purpose

Core runtime helpers for reasoning sessions, telemetry, and benchmarking.

## Entry Points

- `benchmarking.py` — reusable benchmark workflows and report IO
- `cost_tracker.py` — cost and savings accounting

## Key Contracts

- benchmark helpers must keep report JSON stable enough for CLI compare/report/export
- runtime helpers should stay host-neutral and reusable from CLI, SDK, and service layers
