# Deferred Items — Phase 04 Historical Code Intelligence

## 04-04 Execution

- **Pre-existing typecheck debt:** `make typecheck` still fails outside Wave 4 scope in `src/atelier/infra/code_intel/git_history/{__init__,renames,walker}.py` and longstanding union-typing call sites in `src/atelier/core/capabilities/code_context/engine.py`, `src/atelier/core/capabilities/archival_recall/symbol_recall.py`, `src/atelier/core/capabilities/tool_supervision/symbol_edit.py`, and `src/benchmarks/code_intel/recall_symbol_bench.py`.
- **Pre-existing test debt:** `make test` reported multiple unrelated failures across the wider repository before completion; Wave 4 targeted suites passed, but the full suite remains blocked by existing red tests outside the files owned by `04-04-PLAN.md`.
