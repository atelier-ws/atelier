# Fix: explore tool returns test files before implementation files

## Environment note

The `.env` files (credentials) are symlinked by the fitness script automatically
— you do NOT need to set up credentials manually. Just edit `engine.py` and let
the harness measure fitness.

## Problem

When the agent queries `explore("trim_docstring admindocs")` on a Django codebase,
the result shows `tests/admin_docs/test_utils.py — TestUtils [class]` **before**
`django/contrib/admindocs/utils.py — trim_docstring [function]`.

This forces the agent to fall back to `grep` → `read` → `edit` (extra turns, extra
cost) instead of seeing the function body immediately and editing directly.

## Root cause

FTS5 BM25 tokenises on underscores: `trim_docstring` → ["trim", "docstring"].
The `TestUtils` class body in the test file references these terms far more times
(method names, assertions, docstrings) than the actual definition. So BM25 ranks
the test class above the one function that defines the symbol.

The existing single-token exact-lookup path (around L3091) already fixes this for
bare queries like `explore("trim_docstring")` — it does a direct lexical lookup
and pins the definition to the front. But for **multi-word** queries like
`explore("trim_docstring admindocs")`, the path is skipped (`_SYMBOL_QUERY_RE`
requires no spaces).

## Current state (HEAD)

File: `src/atelier/core/capabilities/code_context/engine.py`

Key code around **L3089–3105**:

```python
exact_hits = _exact_symbol_hits(raw_symbols, query)
if not exact_hits and _SYMBOL_QUERY_RE.match(query.strip()):  # single-token only!
    lexical_hits = self.search_symbols(
        query, limit=max(bounded_max_symbols, 10),
        mode="lexical", snippet="none", auto_index=False,
    )
    exact_hits = _exact_symbol_hits(lexical_hits, query)
```

For `query="trim_docstring admindocs"`, neither branch fires (space in query).
`trim_docstring` from `utils.py` ends up with a lower BM25 score than `TestUtils`
from `test_utils.py` and may not appear in the result at all.

## Goal

Extend the exact-name lookup to **also probe individual tokens** from multi-word
queries. Specifically: when the full query doesn’t match a symbol name, split the
query on whitespace and probe each **compound-identifier token** (contains an
internal `_` or camelCase boundary, e.g. `trim_docstring`, `MyClass`) for an
exact symbol-name match. Pin any matches to the front via `exact_ids` — they
survive the relevance floor and budget trim and appear first in the output.

This directly lets the agent see the `trim_docstring` function body in the first
explore call and skip the grep→read fallback.

## Constraint

- Only modify `src/atelier/core/capabilities/code_context/engine.py`
- All existing tests must pass: `uv run pytest tests/core/test_code_context.py -q`
- Do NOT probe plain English words ("admindocs", "default", "role") — only tokens
  that look like code identifiers (see `_COMPOUND_IDENT_RE` hint below)
- Do NOT break concept queries (multi-word concept queries still need anchor/family
  recall from zoekt/semantic channels when there are no exact hits)

## Implementation sketch

Add an `elif` branch right after the existing single-token branch:

```python
elif not exact_hits and " " in query.strip():
    # Multi-word query: probe each compound-identifier token for an exact
    # symbol-name match so that e.g. 'trim_docstring admindocs' pins the
    # trim_docstring definition even though the full query has a space.
    _COMPOUND_IDENT_RE = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]|[a-z][A-Z]")
    token_hits: list[SymbolRecord] = []
    seen_ids: set[str] = set()
    for token in query.strip().split():
        # Only probe compound identifiers (trim_docstring, MyClass) not plain
        # English words (admindocs, default, role) -- guards the anchor/recall path.
        if len(token) <= 3 or not _SYMBOL_QUERY_RE.match(token) or not _COMPOUND_IDENT_RE.search(token):
            continue
        lhits = self.search_symbols(
            token,
            limit=max(bounded_max_symbols, 10),
            mode="lexical", snippet="none", auto_index=False,
        )
        for r in _exact_symbol_hits(lhits, token):
            if r.symbol_id not in seen_ids:
                seen_ids.add(r.symbol_id)
                token_hits.append(r)
    exact_hits = token_hits
```

Move `_COMPOUND_IDENT_RE` to module level (near `_SYMBOL_QUERY_RE`) if you prefer.

## Fitness measurement

```bash
bash scripts/swarm_explore_fitness.sh
```

Outputs the benchmark `cost_usd` as a float (lower = better). Exits 1 if the
task was not solved correctly (gate). Baseline is measured automatically from
HEAD (~$0.1465) before wave 1.

Target: **≤ $0.098** (match baseline grep-agent cost), task solved correctly.
