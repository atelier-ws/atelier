# Memory Interop

## Purpose

Wrap external memory systems without turning Atelier into a memory layer.

## Entry Points

- `openmemory.py` — OpenMemory bridge wrapper
- `mem0.py` — Mem0 scaffold
- `generic_vector_memory.py` — generic host-supplied vector memory scaffold

## Key Contracts

- memory stores facts
- Atelier stores reasoning artifacts
- sync is explicit and opt-in
