# Fix: explore tool returns test files before implementation files

## Problem

When the agent queries `explore("trim_docstring admindocs")` on a Django codebase,
the result shows `tests/admin_docs/test_utils.py — TestUtils [class]` **before**
`django/contrib/admindocs/utils.py — trim_docstring [function]`.

This forces the agent to fall back to `grep` → `read` → `edit` (extra turns, extra cost)
instead of seeing the function body immediately and editing it directly.

## Root cause

FTS5 BM25 tokenises on underscores: `trim_docstring` → ["trim", "docstring"].
The `TestUtils` class body in the test file references these terms many more times
(test method names, assertions, docstrings) than the actual implementation file.
So BM25 ranks the test class higher than the function definition.

## Current state (HEAD)

The code already:
- Applies test-file penalty (0.5x score) **before** computing the relevance floor  
- Uses a floor derived from non-test symbol scores only  
- Hard-removes minified/vendor files  

See `src/atelier/core/capabilities/code_context/engine.py`, function
`_tool_explore_impl`, around lines 3080–3220.

Current benchmark cost: **~$0.1465** for django__django-12155.
Baseline (grep-based coding agent): **$0.098**.

## Goal

Make explore return `utils.py::trim_docstring` **with its full body** as the first
result for queries like "trim_docstring admindocs", so the agent can:
1. explore once → see the function  
2. edit directly (correct first try)  
3. run tests once to confirm  

Target: **≤$0.098** cost, task still solved correctly.

## Constraints

- Only modify `src/atelier/core/capabilities/code_context/engine.py`  
- All existing tests must pass: `uv run pytest tests/core/test_code_context.py -q`  
- Do not hardcode Django-specific logic; the fix must be general  
- Do not reduce explore quality for other query types  

## Approaches to consider (pick one or combine)

### A — Per-token lexical exact lookup
For multi-word queries, split on whitespace and check each identifier-like token
against symbol names via a direct lexical lookup (same as the existing
single-token path). Pin any exact name hits to the front (they'll survive the
floor and budget trim because they're in `exact_ids`).

The key code location:
```python
# around line 3091:
if not exact_hits and _SYMBOL_QUERY_RE.match(query.strip()):
    lexical_hits = self.search_symbols(query, limit=..., mode="lexical", ...)
    exact_hits = _exact_symbol_hits(lexical_hits, query)
```
Extend this to also try each whitespace-delimited token of a multi-word query
(guard: token must match `_SYMBOL_QUERY_RE` and len > 3 to avoid noise).

### B — Budget trim protection for definition symbols
The budget trim loop (`while len(files_payload) > 1 and total > budget: files_payload.pop()`)
drops the last file. If the definition file happens to be last (low BM25 score),
it gets dropped even though it's the most important result.
Fix: before the trim loop, move any file containing an exact/token-exact definition
hit to `files_payload[0]` so it is never popped.

### C — FTS5 field-weighted query
The `search_symbols` call uses the symbol FTS5 index. Adding a field prefix
`symbol_name:` to the query (FTS5 syntax: `symbol_name : trim_docstring`) would
boost matches in the `symbol_name` column vs body/snippet matches. Check whether
the current FTS5 schema has named columns and if `search_symbols` supports
field-qualified queries.

### D — Score normalization before floor
Instead of a fixed 0.5x penalty for test files, dynamically compute a penalty that
guarantees the best non-test score always exceeds the best test score:
`penalty = (best_non_test_score / best_test_score) * 0.9` (so test files rank
just below impl files regardless of the raw score gap).

## Fitness measurement

```bash
bash scripts/swarm_explore_fitness.sh
```

Outputs the benchmark `cost_usd` as a float. Exits 1 if the task was not solved
correctly (gate). Lower cost = better.

Baseline is measured automatically from HEAD before wave 1.
