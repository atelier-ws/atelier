# failure_analysis

## Purpose

Cluster recurring failed traces, infer likely root causes, and propose actionable remediations.

## Entry Point

`__init__.py` re-exports `FailureAnalysisCapability`.

## Module Layout

- `capability.py` - clustering, fingerprint normalization, incident matching, suggested fixes.

## Key Contracts

- `analyze(domain=None, lookback=200, min_cluster_size=2)` -> clustered incident report.
- `analyze_for_error(task, error, domain=None, lookback=200)` -> best matching incident for a live failure.
- Suggestions are fail-open and always return fallback fixes if history is sparse.

## Where to look next

- `src/atelier/core/runtime/engine.py`
- `src/atelier/gateway/adapters/mcp_server.py`
