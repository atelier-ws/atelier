# Validation Matrix

| Change surface | Minimum validation |
| --- | --- |
| Python runtime or CLI | `make lint && make typecheck && make test` |
| Code-intel engine or MCP `code` ops | `uv run pytest tests/core/test_code_context.py tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_mcp_tool_handlers.py tests/gateway/test_savings_api.py -q && uv run pytest tests/benchmarks/code_intel/test_symbol_search_bench.py::test_scip_vs_local_latency_ratio_min_100x tests/benchmarks/code_intel/test_symbol_search_bench.py::test_scip_navigation_tokens_at_most_half_of_local_baseline tests/benchmarks/code_intel/test_symbol_search_bench.py::test_symbol_search_uses_at_most_25pct_of_text_search_tokens -q && make lint && make typecheck && make test` |
| Frontend UI or API usage | `cd frontend && npm run build && npm run test` |
| Docs and repo scaffolding | `make docs-check && make check-agent-context` |
| Host instruction sources or generated host files | `make sync-agent-context && make check-agent-context` |
| Worktree bootstrap or runtime evidence scripts | `make docs-check && uv run pytest tests/gateway/test_generated_agent_contexts.py -q` |

## Notes

- Run the smallest targeted check first while iterating, then the broader project checks before concluding.
- `make verify` is the wide gate for repository changes and should include docs governance.
- Keep new validation paths inside existing tools and repo scripts whenever possible.
