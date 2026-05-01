# context_compression

## Purpose

Compresses run-ledger events into a token-budgeted, high-signal context block for next-step prompts.

## Entry Point

`__init__.py` re-exports `ContextCompressionCapability`.

## Module Layout

| File               | Responsibility                                                                               |
| ------------------ | -------------------------------------------------------------------------------------------- |
| `capability.py`    | Main orchestrator: event normalization, protected-event preservation, token-budget selection |
| `scoring.py`       | Event importance scoring (kind weight + recency + error-chain adjustments)                   |
| `deduplication.py` | Exact duplicate collapse via content digest; optional MinHash near-duplicate suppression     |
| `models.py`        | `DroppedContext`, `EventScore`, `CompressionResult`                                          |

## Key Contracts

- `compress(ledger)` -> `dict[str, Any]` via `context_report()`
- `compress_with_provenance(ledger, token_budget=...)` -> `CompressionResult`
- Token accounting uses `tiktoken` when available; falls back to char heuristics
- Error and tail events are always protected from dropping

## Notes

- `blake3` is used for fast exact-content fingerprints when installed (SHA-256 fallback otherwise)
- `datasketch` MinHash is optional acceleration for similarity deduplication

## Where to look next

- `src/atelier/core/runtime/engine.py`
- `src/atelier/core/foundation/models.py`
