# Swarm spec: improve explore retrieval MRR

## Goal
Improve the MRR (Mean Reciprocal Rank) of `tool_explore` on 566 SWE-bench
(query, gold-file) pairs across 5 repos. The fitness command measures MRR
directly — maximize it.

## Baseline
- Lexical-only (current HEAD): **MRR 0.2288**, hit@1 0.2191
- With zoekt trigram fusion (zoekt servers pre-built): **MRR 0.3631**, hit@1 0.3534
- CodeGraph cg_explore reference: 0.3415
- Target: push MRR as high as possible; hit@1 0.8+ is the stretch goal

## What has already been tried (do NOT re-implement)
- Token-level exact pinning (`token_exact_ids`) — already landed in engine.py
- Graph anchor channel (callers of seed symbols) — tried, HURTS (−0.9 pp): noisy,
  callers go up the call graph, wrong direction for bug-fix queries
- Two-tier impl/test sort + non-test floor — reverted; interacts badly with token_pin

## Where the code lives
All retrieval logic is in ONE file:
`src/atelier/core/capabilities/code_context/engine.py`

Key methods:
- `_tool_explore_impl` (~L3150): the main pipeline — FTS seeds → anchor fusion
  (zoekt + semantic) → rank → filter → render
- `_search_symbols_local` (~L4637): multi-channel FTS/BM25 + centrality scoring
- `_zoekt_candidate_files` (~L5812): zoekt trigram anchor channel
- `_semantic_candidate_files` (~L5853): embedding NN anchor channel
- `_symbol_centrality_map` (~L8069): global PageRank scores (static; not per-query)
- `call_graph_centrality` / `_find_callers_local`: call graph data
- DB tables available: `symbols`, `call_edges`, `references`, `symbol_fts`

## High-value ideas to explore (pick ONE per worker)

### Idea A — Per-query call-graph propagation (RWR)
Implement CodeGraph-style Random Walk with Restart on the call graph:
1. After FTS gives seed symbols, collect their names
2. Find DEFINITION files of symbols those seeds CALL (callees going DOWN,
   not callers going UP — that's the direction that was wrong before)
   Query: `SELECT DISTINCT s.file_path FROM call_edges ce JOIN symbols s
   ON s.repo_id=ce.repo_id AND s.symbol_name=ce.callee_short_name
   WHERE ce.repo_id=? AND ce.caller_symbol_name IN (seed_names)
   AND s.file_path != seed_file` — gets files the seeds depend on
3. Add those as high-priority anchor candidates (prepend before zoekt)
Filter out high-fanout callees (>20 distinct def files = too generic).

### Idea B — IDF-weighted seed selection for anchor expansion
Currently `bounded_max_symbols=20` FTS hits seed the anchor expansion.
Many low-IDF hits (e.g., symbols named `get`, `set`, `save`) add noise.
Better: score each FTS hit by `bm25_score * (1 / log(1 + doc_freq))`
so rarer symbols seed the zoekt/graph expansion, not ubiquitous ones.
The IDF is already computed in `_discriminative_fts_terms`; pipe it into
choosing WHICH symbols become anchor seeds.

### Idea C — Score floor grounded in definition symbols only
The current relevance floor uses `top_score * frac` where top_score may
come from a test file (inflated BM25). Fix: compute the floor only from
definition-kind symbols (class/function/method) in non-test files.
Then apply the floor to cut noise without eliminating the impl file.
This is the non-test-floor idea but applied ONLY to the floor calculation,
not the two-tier sort (which is the part that interacted badly).

### Idea D — Boost symbols whose file is a direct import of a seed file
For each FTS seed symbol, find files that IMPORT the seed's file
(via the `references` table: `symbol_name LIKE '%.%'` where the
module part matches the seed's file stem). Files that explicitly import
the seed file are likely closely related. Boost their symbols' scores by
a fixed amount (e.g., +50 adjustment in `_search_symbols_local`).

### Idea E — Widen anchor budget for zoekt only
Currently `anchor_budget = max(bounded_max_files * 2, 12)` caps zoekt at 12
files. Zoekt has already shown it's the biggest driver (+14pp). Try
`anchor_budget = max(bounded_max_files * 4, 24)` — give zoekt more candidates
so the 3-files-per-file cap in anchor injection has more to pick from.
Also try raising `max_per_file=2` in anchor injection to `max_per_file=3`.

## Fitness command (run from repo root inside worktree)
```bash
PATH=$HOME/go/bin:$PATH ATELIER_ZOEKT_MODE=installed ATELIER_ZOEKT_LOC_THRESHOLD=1 FITNESS_WORKERS=4 uv run python benchmarks/codebench/fitness_explore_mrr.py
```
Outputs one JSON line to stdout: `{"mrr": 0.XXXX, "hit1": ..., ...}`
Metric to maximize: `mrr`.

## Constraints
- Only edit `src/atelier/core/capabilities/code_context/engine.py`
- Do NOT run full test suite (tests are slow and pre-existing failures exist)
- Keep changes minimal and targeted — one idea per worker
- The fitness run takes ~30 seconds with FITNESS_WORKERS=4
- Zoekt servers are already running for the bench repos at /tmp/idx_ws_*/
- Bench pairs are at /tmp/bench_pairs_multi.json (shared, read-only)

## Swarm convergence context
- Wave: 3 of a continuous swarm run.
- Accepted improvements already integrated into the current base:
  - wave-01-run-02: The change successfully implements the spirit of Idea B by using token-count as a proxy for IDF - longer multi-token names that match are inherently more discriminative than common single-token names, and boosting them improves retrieval quality.
  - wave-02-run-03: The fitness result shows this change regressed MRR from 0.379 to 0.3163 (-16.5%), so the implementation is complete and measured - it just didn't improve retrieval quality.
- Latest evaluator summary: Accepted measured winner wave-02-run-03 (metric 0.386 vs baseline 0.379, improvement +0.007).
- Primary focus for this child: explore the best remaining improvement opportunity without duplicating already accepted work.
- This is candidate 3 of 3; bias toward a distinct angle rather than repeating another likely attempt.
- Prefer independent improvements that can stack with already accepted changes.
- If you detect a conflict with accepted work, choose a compatible alternative rather than reverting the base.
