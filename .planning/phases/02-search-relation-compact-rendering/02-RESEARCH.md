# Phase 2 Research: Search/Relation Compact Rendering

**Researched:** 2026-05-23  
**Phase:** 2 - Search/Relation Compact Rendering

## Objective

Define a safe implementation path to reduce token overhead in search/relation outputs while preserving retrieval quality and compatibility with existing `code` MCP operations.

## Source Inputs

- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/STATE.md`
- `.planning/phases/01-output-policy-foundation/01-CONTEXT.md`
- `.planning/phases/01-output-policy-foundation/01-01-SUMMARY.md`
- `src/atelier/core/capabilities/code_context/engine.py`
- `src/atelier/core/capabilities/code_context/models.py`
- `tests/core/test_code_context.py`
- `tests/benchmarks/test_code_search_ab_real.py`

## Key Findings

1. **Policy foundation is in place.** Phase 1 introduced reusable output-policy caps; Phase 2 should apply these more aggressively to search/relation render payload shape.
2. **Main reduction opportunities:** search item fields, relation payload field breadth, and grouping verbosity in usages/call-graph outputs.
3. **Critical non-regression rule:** keep retrieval/ranking depth unchanged and optimize only emitted payload shape.
4. **Best landing zones:** `_pack_items_payload`, `tool_search`, `find_references`, and `_tool_call_graph` in `engine.py`.
5. **Validation focus:** regression tests for compact pointer rows and relation payload bounds plus benchmark checks for effective-token deltas.

## Planning Guidance

- Keep all work inside existing `code` ops.
- Maintain disambiguation and error payload usability while reducing optional metadata.
- Add explicit tests to guard against accidental recall regressions from over-trimming.
