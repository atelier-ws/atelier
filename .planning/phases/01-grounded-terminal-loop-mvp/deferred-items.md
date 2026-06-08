# Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Tooling | `make lint` fails on pre-existing unrelated issues in `benchmarks/atelierbench/run.py` (`UP035`) and `scripts/extract_flow.py` (`BLE001`) | Deferred | 2026-06-02 |
| Tooling | `make typecheck` fails on a pre-existing duplicate `benchmarks` module conflict between `benchmarks/__init__.py` and `src/benchmarks/__init__.py` | Deferred | 2026-06-02 |
| Tests | Full `tests/gateway/test_p0_mcp_surfaces.py -q -x` fails on pre-existing `test_tool_code_search_accepts_hardened_params` ordering `src/benchmarks/code_intel/cost_discipline.py` ahead of the fixture repo result | Deferred | 2026-06-02 |
| Tests | Full `tests/gateway/test_mcp_tool_handlers.py -q -x` fails on pre-existing `test_context_reuses_bootstrap_blocks_instead_of_enqueuing_duplicate_work` returning an empty bootstrap context plus follow-on tree-sitter thread warnings | Deferred | 2026-06-02 |
