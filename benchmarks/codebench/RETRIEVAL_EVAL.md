# Retrieval eval — explore/search MRR + latency

Offline eval of Atelier's code retrieval, scored by **rank-of-gold-file** over
mined SWE-bench `(query, gold-file)` pairs across the diverse-5 repos
(django, astropy, xarray, pytest, scikit-learn). Reports **MRR / hit@1 / hit@3**
and **per-query latency**. Use it to compare retrieval channels and to guard
against regressions when changing `_search_symbols_local` / fusion / ranking.

## Channels

| # | Channel | Harness | What it exercises |
|---|---------|---------|-------------------|
| 1 | **Lexical** | `fitness_explore_mrr.py` | `tool_explore` symbol FTS/trigram + ranking (no zoekt binaries on PATH) |
| 2 | **+ Zoekt fusion** | `fitness_explore_mrr.py` (zoekt installed) | adds zoekt trigram-anchor files to the fusion (auto-on when binaries resolve) |
| 3 | **BGE semantic** | `eval_semantic_mrr.py` | standalone embedding retrieval (BGE-Code-v1) over the pre-built corpus |

Channels 1–2 are the SHIPPED `tool_explore` path. Channel 3 is a standalone probe
(semantic is not yet fused into explore) answering "does the embedder help these
queries?" before investing in fusion.

## Latest results (single-worker, n=566 pairs)

| Channel | MRR | hit@1 | hit@3 | latency / query |
|---------|-----|-------|-------|-----------------|
| baseline (pre-work) | 0.220 | — | — | — |
| 1. Lexical (IDF + df-budget) | 0.394 | 0.315 | 0.429 | 247 ms explore · 48 ms search-core |
| 2. + Zoekt fusion | **0.478** | 0.392 | 0.505 | 632 ms explore (+385 ms zoekt subprocess) |
| 3. BGE semantic (standalone) | 0.446¹ | 0.327 | 0.498 | 16 ms embed+cosine (GPU) |

¹ 0.456 excluding scikit-learn: its gold files (`sklearn/decomposition/dict_learning.py`,
`examples/…`) are absent from the pre-built BGE corpus (coverage gap, n=12), so semantic
cannot be scored there.

## Provisioning (one-time)

- **Pairs + per-repo index DBs**: `scripts/_provision_repos.py` writes
  `benchmarks/codebench/data/bench_pairs_multi.json` (maps each repo to a prebuilt read-only `(ws, db)`).
  Override the path with `EVAL_PAIRS` / the harness reads `benchmarks/codebench/data/bench_pairs_multi.json`.
- **Zoekt (channel 2)**: install the binaries on `PATH` and build per-repo indexes:

  ```bash
  GOBIN=$HOME/go/bin go install github.com/sourcegraph/zoekt/cmd/{zoekt,zoekt-index,zoekt-git-index,zoekt-webserver}@latest
  # build an index per repo workspace (ws): ZoektSupervisor(ws).server.ensure_started_and_build()
  ```

- **BGE corpus (channel 3)**: pre-built vectors live in
  `benchmarks/embedding/data/multi_repo/emb_bge_<repo>.npy` + `corpus_<repo>.jsonl`
  (built by `benchmarks/embedding/bench_multi_repo.py`). Needs `sentence-transformers`
  - `torch` (see `benchmarks/embedding/requirements_hf.txt`) — NOT the project venv.

## Running

```bash
# Channel 1 (lexical) — single-worker is required for trustworthy latency numbers.
FITNESS_WORKERS=1 uv run python benchmarks/codebench/fitness_explore_mrr.py

# Channel 2 (+ zoekt) — same command with zoekt on PATH; lower the LOC gate so
# sub-500k-LOC repos route to zoekt.
PATH="$HOME/go/bin:$PATH" ATELIER_ZOEKT_MODE=installed ATELIER_ZOEKT_LOC_THRESHOLD=1 \
  FITNESS_WORKERS=1 uv run python benchmarks/codebench/fitness_explore_mrr.py

# Channel 3 (semantic) — run with the benchmark env that has sentence-transformers.
python3 benchmarks/codebench/eval_semantic_mrr.py
```

Each prints one JSON line: `{mrr, hit1, hit3, n, latency_ms:{mean,p50,p95,max,over_100ms}, by_repo}`.
`FITNESS_SAMPLE=N` caps unique queries/repo for a fast signal; `FITNESS_REPO=django`
filters to one repo.

## Notes / caveats

- **Latency** is per-query wall-clock; only trustworthy with `FITNESS_WORKERS=1`
  (parallel workers contend on CPU and inflate each call).
- **Zoekt latency** is dominated by a per-query subprocess; a persistent
  `zoekt-webserver` would cut it. The 500k-LOC default gate keeps normal repos
  off zoekt by default.
- The harness stubs the retrieval cache (force-miss) so each run measures its own
  ranking, and the per-repo index DBs stay effectively read-only.
