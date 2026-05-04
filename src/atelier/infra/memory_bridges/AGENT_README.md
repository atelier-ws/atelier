# Memory Bridges

## Purpose

Normalize external memory providers behind a shared `MemorySyncResult` contract.

## Entry Points

- `openmemory.py` — Adapter over gateway OpenMemory bridge APIs.
- `mem0.py` — Mem0 adapter scaffold.
- `generic_vector_memory.py` — generic host vector memory adapter scaffold.

## Key Contracts

- `fetch_context()` returns JSON-serialized bridge data in `context`.
- `push_procedural_lesson()` links trace-to-memory pointers for downstream retrieval.
- Adapters expose `ok/skipped/source/context/detail` consistently.

## Where To Look Next

- `src/atelier/gateway/integrations/openmemory.py`
- `src/atelier/infra/memory_bridges/base.py`
