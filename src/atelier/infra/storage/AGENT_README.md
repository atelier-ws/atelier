# Storage Backends

## Purpose

Provide persistence backends and vector utilities used by runtime retrieval.

## Entry Points

- `factory.py` — store selection from config/env.
- `sqlite_store.py` — local SQLite persistence.
- `postgres_store.py` — Postgres-backed persistence.
- `vector.py` — embedding generation and cosine similarity helpers.

## Vector Contract

- `generate_embedding()` supports `local` and `openai` providers.
- `stub_embedding()` is a backward-compatible alias to `generate_embedding()`.
- `is_vector_enabled()` gates vector features for callers.

## Where To Look Next

- `src/atelier/core/runtime/engine.py`
- `tests/core/test_retriever_vector.py`
