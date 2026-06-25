# Swarm task: maximize lexical retrieval MRR for `explore` (no embeddings)

You are one isolated candidate in an optimization swarm. Make ONE focused,
generic improvement to Atelier's **lexical** code-retrieval ranking so the
shipped `explore` tool ranks the gold target file higher. A fitness harness
scores your worktree automatically; the best candidate per wave is kept and the
next wave builds on it.

## Objective (how you are scored)

Fitness = mean reciprocal rank (MRR) of the gold true file among the files
`tool_explore` returns, over ~566 real (query, repo) pairs across 6 SWE-bench
repos (django, pytest, astropy, scikit-learn, xarray, sympy). Higher is better.
The harness runs:

    PYTHONPATH=src:. uv run python benchmarks/codebench/fitness_explore_mrr.py

and parses `json:mrr`. It also reports `by_repo` — **a winning change lifts the
average WITHOUT cratering any single repo.** Baseline (HEAD) MRR is ~0.30.
Target: push it as high as possible (stretch goal 0.8).

## The lever — change only query-time ranking

Edit only:  `src/atelier/core/capabilities/code_context/*.py`
The core is `_search_symbols_local` (the multi-channel scorer:
exact/FTS/substring/path/fuzzy + kind boost + per-term coverage + a call-graph
centrality bonus + a per-token name-match bonus) and the `tool_explore`
assembly (zoekt-anchor fusion, sibling-family completion, file-diversity cap,
file ranking). Improving `_search_symbols_local` lifts both `search` and
`explore`; the explore-only assembly steps (family/diversity/file-cap) can
*dilute* the true file out of the top — tune them too.

## Hard constraints

- **Generic, not benchmark-overfit.** No hardcoding repo names, file paths,
  or query strings. The multi-repo fitness exists to catch overfit — a change
  that only helps django will be rejected. Reason from retrieval principles.
- **Lexical only.** Do NOT touch or enable the embedding/semantic path
  (`_search_symbols_semantic_*`, ANN, Ollama). That is a separate arm. Semantic
  is OFF here and must stay off.
- **Query-time only.** The fitness reuses prebuilt indexes; do NOT change
  index-time symbol extraction (it won't be measured and may break routing).
- **Gate must pass:** `uv run pytest -q -m "not slow" tests/core/test_code_context.py tests/gateway/test_p0_mcp_surfaces.py`
  and keep `uv run mypy src/atelier/core/capabilities/code_context/engine.py` clean.
- **Surgical + hard-remove.** Smallest change that works; delete dead code, no
  compat shims, no new config knobs unless essential.

## TOP LEVER (from a CodeGraph differential — prioritize this)

Empirically, CodeGraph's edge on these queries is **recall via robust query-term
extraction**, NOT ranking or path signals. The queries are often grep-style:
`def _sqlite_datetime_parse|def _sqlite_date_trunc`, `^class (ExceptionChainRepr|ReprExceptionInfo)`,
`_convert_tzname_to_sql\b`. Atelier ingests the raw regex — the metacharacters
(`def`, `class`, `^`, `|`, `(`, `)`, `\b`, `*`, `$`) pollute its terms and it
fails to recall the right file AT ALL (returns unrelated test models). CodeGraph
strips that syntax and extracts the clean identifiers, then matches them.

**The highest-value change is almost certainly improving how `search_symbols`
turns a query into terms**: strip regex/code syntax and keywords, split
camelCase/PascalCase/snake/SCREAMING/dot identifiers into subtokens, and match on
those. This is a GENERIC robustness fix (agents paste `def foo`, decorated names,
multi-symbol bags), not benchmark-overfit. Fixing recall on these messy queries
likely recovers the bulk of the gap. Verify with `by_repo` — it should lift
multiple repos, not just django.

## Other directions to consider (after the top lever)

- Stronger query-term coverage / multi-term AND-ing so files matching more
  query tokens rank above incidental single-token matches.
- A path-relevance signal (query tokens matching path components / filename).
- Re-tune the existing magic weights (centrality bonus, per-token name bonus,
  test penalty, kind boosts) — they were hand-picked, likely not optimal.
- Better fuzzy thresholds / damping so noise doesn't outrank exact-ish hits.
- Tune zoekt-anchor fusion (how many anchors, how they seed) for concept
  queries with no lexically-matching symbol name.
- Fix explore's file-cap/diversity/family ordering so the true file isn't
  pushed below filler siblings.

## Workflow

1. Run the fitness once to see the baseline + `by_repo` on your worktree.
2. Form ONE hypothesis, implement it surgically.
3. Re-run the fitness; keep it only if MRR rises and no repo collapses.
4. Ensure the gate passes. Leave the change committed in your worktree.

Report: the hypothesis, the MRR before/after (+ by_repo), and why it generalizes.
